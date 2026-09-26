#!/usr/bin/env python3
"""#419 exact-tree #367 preflight: provider query per exact key, no Hero EV.

This command walks the 38 required nodes of the #388/#419 exact response tree of
scenario #321 (plus the 7 unresolved raise-sizing frontiers) and asks the
hierarchical Model-A provider
(``tools.preflop.model_a_sizing_hierarchical.resolve_exact_context``) for every
node's **exact** key.  For each node it records the exact key, the node identity,
the empirical support, the pooling provenance, the uncertainty band and the
posterior identity.

It is a *preflight*: it never runs the #367 Hero EV runner, never computes a
rollout, an EV or a recommendation, never consumes VALIDATION/TEST and never
mutates an active model pointer.

The admissibility rule implemented here is the **protocol v2** rule
(``FROZEN_VALIDATION_PROTOCOL_V2.json``, amendment
``V2_AMENDMENT_1_CONDITIONAL_NODE_CLOSURE``): a required node is admissible

* either as ``EXACT_EMPIRICAL_STRONG`` -- the unchanged layer-A definition
  (``L0_EXACT_KEY`` meeting both the 20-observation and the 20-distinct-hands
  thresholds, supported only by its own exact key); it is *never* counted as
  exact support for any other key;
* or as ``EXACT_HIERARCHICAL_ESTIMATE`` -- the exact key identity is preserved,
  the counted support stays exact-key-only, pooling only feeds the Dirichlet
  prior, and every frozen layer-B admissibility gate
  (``EXACT_KEY_IDENTITY``, ``POOLING_PROVENANCE``, ``POOLING_LEVEL``,
  ``EFFECTIVE_SAMPLE_SIZE``, ``UNCERTAINTY``, ``CALIBRATION``,
  ``RAISE_SIZING_FRONTIER``) passes.

``required_tree_complete`` is true only when every required node is closed *and*
no raise-sizing frontier stays unresolved; otherwise it is false and carries
reason codes.  A fail-closed node is never repaired by lowering a threshold, by
borrowing another key's support, or by a nearest-price / nearest-context /
representative-price / interpolation substitution: every such substitution is
refused and traced.

Crucially this is a *pre-validation* preflight: it consumes no VALIDATION split,
so the frozen ``CALIBRATION`` gate has no measured evidence and therefore fails
closed as ``GATE_UNEVALUATED_PRE_VALIDATION`` for every estimate answer.  That
is deliberate -- an unevaluated layer-B gate may never close a node.

The tool writes its bundle to ``analysis/issue419_hierarchical_tree/
exact_tree_preflight_v2/``.  The superseded ``v1`` bundle
(``exact_tree_preflight/``) is a frozen, pinned v1 surface: it is re-verified
byte-for-byte here and is never rewritten.
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
from tools.repro_preflop_fixture import FIXTURE_PATH  # noqa: E402
from tools.training import audit_hierarchical_tree_sparsity as baseline_tool  # noqa: E402
from tools.training import fit_model_a_preflop_sizing_hierarchical as fit_tool  # noqa: E402
from tools.training.audit_preflop_sizing_support import stable_hash  # noqa: E402

HERE = ROOT / 'analysis/issue419_hierarchical_tree'
# ``OUTPUT``/``NAME``/``SCHEMA`` name the *frozen* v1 preflight bundle.  Other
# #419 tools (the terminal decision and its tests) still bind to those names, so
# they keep pointing at the frozen v1 bytes; they are re-verified, never
# rewritten, by this v2 tool.
OUTPUT = HERE / 'exact_tree_preflight'
NAME = 'EXACT_TREE_PREFLIGHT.json'
SUMMARY_NAME = 'SUMMARY.md'
INDEX_NAME = 'ARTIFACTS.json'
SOURCE_PATH = Path(__file__).resolve()

# The v2 preflight bundle this tool produces: schema v2, protocol-v2
# admissibility (conditional exact-context estimate node closure).
V2_OUTPUT = HERE / 'exact_tree_preflight_v2'
V2_NAME = 'EXACT_TREE_PREFLIGHT_V2.json'
V2_SCHEMA = 'poker-issue419-exact-tree-preflight/v2'

# Pinned bytes of the frozen v1 preflight bundle: the superseded revision is
# immutable evidence and must hash back to these digests on every run.
V1_PREFLIGHT_SHA256 = '456d85be57b910d3a56cb0160ba0ba35c988f7f69da9f965f0a887aaac473ae6'
V1_SUMMARY_SHA256 = '3b87d9bcc366c35e97bde6a4be350704a0cf2eecadb464d5ac321298443778df'
V1_INDEX_SHA256 = '97e90eac0a9302f1d0b304fa698f5179c7c0ee98ad52ebe307a911d9ccbfa5be'
V1_BYTE_SHA256 = '69c99a8b37589f1687b7e980344c9a79d69bbcd45be0a53ffd59bfea0ab583b3'

# Frozen protocol v2 (protocol v1 + amendment V2_AMENDMENT_1) and its
# machine-readable layer-B admissibility gates.
PROTOCOL_V2_PATH = HERE / 'validation_protocol_v2' / 'FROZEN_VALIDATION_PROTOCOL_V2.json'
PROTOCOL_V2_SCHEMA = 'poker-hierarchical-frozen-validation-protocol/v2'
PROTOCOL_V2_STATUS = 'AUTHORED_AFTER_VALIDATION_READ_NO_THRESHOLD_CHANGE'
PROTOCOL_V2_BYTE_SHA256 = (
    '74b8a006ae84f8b9b22913ef76977e95f08992feb9765639a46d1ac49eb87350'
)
PROTOCOL_V2_CANONICAL_PAYLOAD_SHA256 = (
    'cb598a9fc2353aa78f19a7263a62a8ccbdba60eb400264787e896d0c232f19de'
)
PROTOCOL_V2_AMENDMENT_ID = 'V2_AMENDMENT_1_CONDITIONAL_NODE_CLOSURE'
NODE_CLOSURE_RULE_ID = 'NODE_CLOSES_IFF_ALL_FROZEN_LAYER_B_GATES_PASS'
NODE_CLOSURE_VALUE = 'CONDITIONAL'

LAYER_B_GATE_IDS = (
    'EXACT_KEY_IDENTITY',
    'POOLING_PROVENANCE',
    'POOLING_LEVEL',
    'EFFECTIVE_SAMPLE_SIZE',
    'UNCERTAINTY',
    'CALIBRATION',
    'RAISE_SIZING_FRONTIER',
)
LAYER_B_GATE_REASON_CODES = (
    'REFUSED_EXACT_KEY_IDENTITY',
    'REFUSED_POOLING_PROVENANCE',
    'REFUSED_POOLING_LEVEL',
    'REFUSED_EFFECTIVE_SAMPLE_SIZE',
    'REFUSED_UNCERTAINTY',
    'REFUSED_CALIBRATION',
    'REFUSED_RAISE_SIZING_FRONTIER',
)
LAYER_B_GATE_REASON_CODE_BY_ID = dict(zip(LAYER_B_GATE_IDS, LAYER_B_GATE_REASON_CODES))

MAX_POOLING_DEPTH = 4
MAX_POOLING_LEVEL_FOR_ESTIMATE = 'L4_POSITION_PRICE_PRIOR'
POOLING_PROVENANCE_FIELDS = (
    'level',
    'source_key',
    'source_observations',
    'source_distinct_hands',
    'retained_axes',
    'pooled_axes',
)
CALIBRATION_EVIDENCE_SOURCE = 'UNAVAILABLE_IN_THIS_TRAIN_ONLY_PREFLIGHT'

# Layer-B gate reason codes used at the tree level when a closure condition fails.
REFUSED_REQUIRED_NODE_OPEN = 'REFUSED_REQUIRED_NODE_OPEN'
REFUSED_UNRESOLVED_RAISE_SIZING_FRONTIER = 'REFUSED_UNRESOLVED_RAISE_SIZING_FRONTIER'
REFUSED_TREE_ENUMERATION_INCOMPLETE = 'REFUSED_TREE_ENUMERATION_INCOMPLETE'
REFUSED_SUBSTITUTION_APPLIED = 'REFUSED_SUBSTITUTION_APPLIED'
REFUSED_HERO_EV_OR_RECOMMENDATION = 'REFUSED_HERO_EV_OR_RECOMMENDATION'

PROTOCOL_PATH = HERE / 'FROZEN_VALIDATION_PROTOCOL.json'
PROTOCOL_COPY_PATH = HERE / 'validation_protocol' / 'FROZEN_VALIDATION_PROTOCOL.json'
PROTOCOL_DIGEST_PATH = HERE / 'FROZEN_VALIDATION_PROTOCOL.sha256'
PROTOCOL_SCHEMA = 'poker-hierarchical-frozen-validation-protocol/v1'
PROTOCOL_STATUS = 'FROZEN_BEFORE_VALIDATION'
PROTOCOL_BYTE_SHA256 = '69c99a8b37589f1687b7e980344c9a79d69bbcd45be0a53ffd59bfea0ab583b3'
PROTOCOL_CANONICAL_PAYLOAD_SHA256 = (
    'f283ce8dac9fbcfb5485eeb360217af4425fe947f249de652b03d96a13d40db5'
)

CANDIDATE_PATH = HERE / 'fit' / 'CANDIDATE.json'
CANDIDATE_INSTANCE_ID = 'model-a-preflop-sizing-hierarchical-train-fit-419-v1'
CANDIDATE_CANONICAL_SHA256 = (
    '637302885b8119e6b0246d827462c36eb707c6e234d0b652483c956f03360999'
)
CANDIDATE_BYTE_SHA256 = 'c78ae3c434d5f41e50567a131bdfb2b89982243379818709abeb0e5ec2385534'

SCHEMA = 'poker-issue419-exact-tree-preflight/v1'
ISSUE = 419
SOURCE_ISSUE = 388
SCENARIO_ISSUE = 321
SCENARIO_ID = 'kts_sb_two_limp_iso4_three_calls_v1'
ROOT_PATH = ['SB:ISO@5']
INITIAL_ISO_TARGET_TOTAL_BB = 5.0
REQUIRED_NODE_COUNT = 38
UNRESOLVED_FRONTIER_COUNT = 7
MIN_MARGINAL_OBSERVATIONS = 20
MIN_DISTINCT_HANDS = 20
SUPPORT_LEVEL = 'L0_EXACT_KEY'

# The frozen #352 exact-support ISO grid: only the exact requested price may answer.
ADJACENT_ISO_TARGETS_BB = (4.0, 6.0)

# Substitutions that must never be applied when resolving an exact key.
SUBSTITUTION_CLASSES = (
    'NEAREST_PRICE',
    'NEAREST_CONTEXT',
    'REPRESENTATIVE_PRICE',
    'LEGAL_MINIMUM_FALLBACK',
    'INTERPOLATED_PRICE',
    'CROSS_KEY_SUPPORT_BORROWING',
)

# The #367 Hero EV runner and every rollout/EV surface it needs.  This preflight
# must not import or execute any of them; the names are scanned both statically
# (AST) and dynamically (``sys.modules``).
HERO_EV_FORBIDDEN_SYMBOLS = (
    'run_issue367_real_iso_ev',
    'Issue367ScientificProvider',
    'Issue367OpponentPolicy',
    'run_hero_preflop_iso',
    'AdaptiveBudget',
    'paired_adaptive_preflop_ev',
    'hero_preflop_iso_runner',
    'full_hand_arena',
    'full_hand_benchmark',
    'preflop_grid_evaluator',
    'paired_preflop_grid_evaluator',
    'evaluate_alternative',
    'materialize_world',
)
HERO_EV_FORBIDDEN_IMPORT_MARKERS = (
    'issue367',
    'real_iso_ev',
    'paired_adaptive_preflop_ev',
    'hero_preflop_iso_runner',
    'full_hand_arena',
    'full_hand_benchmark',
    'preflop_grid_evaluator',
)

# Holdout loaders a TRAIN-only preflight must never use.  Mirrors the #419 fit
# scan so this command carries the same explicit boundary evidence.
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
DATASET_ROOT = ROOT / 'training' / 'datasets'
HAND_HISTORY_SUFFIXES = frozenset({'jsonl', 'zip', 'snapshots'})

PROTECTED_FILES = (
    'training/registry.json',
    'training/populations/registry.json',
    'training/models/preflop_population_model_v5.json',
    'training/models/postflop_population_model_v5.json',
    'analysis/issue419_hierarchical_tree/FROZEN_VALIDATION_PROTOCOL.json',
)


class PreflightError(RuntimeError):
    """Raised when the exact-tree preflight cannot be produced safely."""


def serialize(payload: Any) -> bytes:
    return (json.dumps(payload, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()


def _load(path: Path) -> dict[str, Any]:
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
            raise PreflightError(f'hand-history/dataset file opened by the preflight: {self}')
        opened.append(_relative(self))
        return original_open(self, *args, **kwargs)

    pathlib.Path.open = guarded_open
    try:
        yield opened
    finally:
        pathlib.Path.open = original_open


def verify_no_holdout_access(source: str | None = None) -> dict[str, Any]:
    """Static proof that this command uses no holdout loader and no holdout path."""
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
        raise PreflightError(f'holdout loader symbol used by the preflight: {hits}')
    bad_imports = sorted(
        name for name in imported
        if any(marker in name.lower() for marker in ('validation', 'holdout'))
    )
    if bad_imports:
        raise PreflightError(f'holdout-looking import in the preflight: {bad_imports}')
    return {
        'check': 'self_source_scan_for_holdout_loaders',
        'result': 'PASS',
        'forbidden_symbols': list(HOLDOUT_LOADER_SYMBOLS),
        'hits': [],
        'holdout_looking_imports': [],
        'detail': (
            'AST scan: the preflight consumes no VALIDATION/TEST loader, imports no '
            'validation/holdout module and opens no hand history'
        ),
    }


def verify_no_hero_ev_execution(source: str | None = None) -> dict[str, Any]:
    """Static proof that this command cannot execute the #367 Hero EV runner."""
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
    hits = sorted(used & set(HERO_EV_FORBIDDEN_SYMBOLS))
    if hits:
        raise PreflightError(f'Hero EV symbol used by the preflight: {hits}')
    bad_imports = sorted(
        name for name in imported
        if any(marker in name.lower() for marker in HERO_EV_FORBIDDEN_IMPORT_MARKERS)
    )
    if bad_imports:
        raise PreflightError(f'Hero EV module imported by the preflight: {bad_imports}')
    return {
        'check': 'self_source_scan_for_hero_ev',
        'result': 'PASS',
        'forbidden_symbols': list(HERO_EV_FORBIDDEN_SYMBOLS),
        'forbidden_import_markers': list(HERO_EV_FORBIDDEN_IMPORT_MARKERS),
        'hits': [],
        'forbidden_modules_imported_during_build': [],
        'runner_module_imported_by_preflight': False,
        'hero_ev_executed': False,
        'recommendation_computed': False,
        'rollouts_executed': 0,
        'ev_values_computed': 0,
        'detail': (
            'AST scan: the preflight imports neither the #367 real ISO EV runner nor any '
            'rollout/EV/adaptive-budget module, and the build re-checks that none appeared '
            'in sys.modules while it ran'
        ),
    }


def hero_ev_modules_present() -> list[str]:
    """Loaded modules that name a Hero EV / rollout / adaptive-budget surface."""
    return sorted(
        name for name in sys.modules
        if any(marker in name.lower() for marker in HERO_EV_FORBIDDEN_IMPORT_MARKERS)
    )


def protected_hashes() -> dict[str, str]:
    return {path: sha256_file(ROOT / path) for path in PROTECTED_FILES}


def verify_frozen_v1_preflight() -> dict[str, Any]:
    """Re-derive the frozen v1 preflight digests; the v1 bundle is never rewritten."""
    expected = {
        NAME: V1_PREFLIGHT_SHA256,
        SUMMARY_NAME: V1_SUMMARY_SHA256,
        INDEX_NAME: V1_INDEX_SHA256,
    }
    digests: dict[str, str] = {}
    for name, pinned in expected.items():
        path = OUTPUT / name
        if not path.is_file():
            raise PreflightError(f'the frozen v1 preflight artifact is missing: {path}')
        actual = sha256_file(path)
        if actual != pinned:
            raise PreflightError(
                f'the frozen v1 preflight artifact drifted: {name} {actual} != {pinned}'
            )
        digests[name] = actual
    return {
        'check': 'frozen_v1_preflight_bytes_re_derived',
        'result': 'PASS',
        'bundle': _relative(OUTPUT),
        'artifacts': digests,
        'never_rewritten': True,
        'superseded_by': _relative(V2_OUTPUT / V2_NAME),
        'reason': (
            'the v1 preflight is pinned as an immutable v1 surface by '
            'FROZEN_VALIDATION_PROTOCOL_V2.json custody and by the T9/T10 terminal decision; this '
            'tool re-verifies those bytes and writes only the v2 bundle'
        ),
    }


def calibration_gate_thresholds(protocol_v2: Mapping[str, Any]) -> dict[str, Any]:
    """The frozen CALIBRATION gate values, read from the v2 protocol, never re-selected."""
    dimension = protocol_v2['layers']['layer_b_exact_context_estimate_admissibility'][
        'admissibility_gates_by_dimension'
    ]['calibration']
    thresholds = protocol_v2['thresholds']
    return {
        'gate_id': dimension['gate_id'],
        'maximum_absolute_ece': float(dimension['maximum_absolute_ece']),
        'maximum_ece_delta_vs_active': float(dimension['maximum_ece_delta_vs_active']),
        'minimum_bin_support_for_a_calibration_claim': int(
            dimension['minimum_bin_support_for_a_calibration_claim']
        ),
        'bins_per_action_class': int(dimension['bins_per_action_class']),
        'report_pooling_level_always': bool(dimension['report_pooling_level_always']),
        'protocol_threshold_maximum_absolute_ece': float(thresholds['maximum_absolute_ece']),
        'protocol_threshold_maximum_ece_delta_vs_active': float(
            thresholds['maximum_ece_delta_vs_active']
        ),
    }


def load_frozen_v2_protocol() -> dict[str, Any]:
    """Verify the frozen v2 protocol identity and its layer-B gate contract."""
    protocol_bytes = PROTOCOL_V2_PATH.read_bytes()
    actual_byte_sha = hashlib.sha256(protocol_bytes).hexdigest()
    if actual_byte_sha != PROTOCOL_V2_BYTE_SHA256:
        raise PreflightError(f'frozen protocol v2 byte hash drifted: {actual_byte_sha}')
    protocol = json.loads(protocol_bytes)
    if protocol.get('schema') != PROTOCOL_V2_SCHEMA:
        raise PreflightError('unexpected frozen protocol v2 schema')
    if protocol.get('status') != PROTOCOL_V2_STATUS:
        raise PreflightError('unexpected frozen protocol v2 status')
    if stable_hash(protocol) != PROTOCOL_V2_CANONICAL_PAYLOAD_SHA256:
        raise PreflightError('frozen protocol v2 canonical payload hash drifted')
    if protocol['v1_provenance']['byte_sha256'] != PROTOCOL_BYTE_SHA256:
        raise PreflightError('protocol v2 does not reference the frozen v1 protocol bytes')

    layer_b = protocol['layers']['layer_b_exact_context_estimate_admissibility']
    if tuple(layer_b['admissibility_gate_ids']) != LAYER_B_GATE_IDS:
        raise PreflightError('the v2 layer-B gate ids drifted')
    if tuple(layer_b['admissibility_gate_reason_codes']) != LAYER_B_GATE_REASON_CODES:
        raise PreflightError('the v2 layer-B gate reason codes drifted')
    if [row['gate_id'] for row in layer_b['admissibility_gates']] != list(LAYER_B_GATE_IDS):
        raise PreflightError('the v2 machine-readable gate order drifted')
    if [row['reason_code'] for row in layer_b['admissibility_gates']] != list(
        LAYER_B_GATE_REASON_CODES
    ):
        raise PreflightError('the v2 machine-readable gate reason codes drifted')
    if tuple(layer_b['identity_axes_retained_at_every_level']) != H.NEVER_MUTUALIZABLE_AXES:
        raise PreflightError('the v2 never-mutualizable identity axes drifted')

    closure = layer_b['node_closure']
    conditional = layer_b['counts_as_a_closed_exact_tree_node']
    if closure['rule_id'] != NODE_CLOSURE_RULE_ID:
        raise PreflightError('the v2 node-closure rule id drifted')
    if conditional['value'] != NODE_CLOSURE_VALUE:
        raise PreflightError('the v2 node closure must stay CONDITIONAL')
    if conditional['true_iff_all_layer_b_gates_pass'] is not True:
        raise PreflightError('the v2 closure must be the conjunction of every layer-B gate')
    if conditional['false_if_any_layer_b_gate_fails'] is not True:
        raise PreflightError('a failing layer-B gate must keep the node open')
    if conditional['default_when_a_gate_is_unevaluated'] is not False:
        raise PreflightError('an unevaluated layer-B gate must fail closed')
    if conditional['unconditionally_closes'] is not False:
        raise PreflightError('an exact-context estimate can never close unconditionally')
    if closure['unresolved_node_closure'] is not False:
        raise PreflightError('an EXACT_UNRESOLVED node never closes')
    if protocol['amendments']['current_amendment_id'] != PROTOCOL_V2_AMENDMENT_ID:
        raise PreflightError('the v2 amendment id drifted')
    if protocol['amendments']['no_gate_value_moved'] is not True:
        raise PreflightError('the v2 amendment must move no gate value')
    if protocol['amendments']['no_threshold_moved'] is not True:
        raise PreflightError('the v2 amendment must move no threshold')
    if protocol['gates']['layer_b_gates_more_permissive_than_v1'] is not False:
        raise PreflightError('a layer-B gate may never be more permissive than v1')
    if protocol['thresholds']['minimum_marginal_observations'] != MIN_MARGINAL_OBSERVATIONS:
        raise PreflightError('the v2 observation threshold drifted')
    if protocol['thresholds']['minimum_distinct_hands'] != MIN_DISTINCT_HANDS:
        raise PreflightError('the v2 distinct-hand threshold drifted')
    pooling_gate = next(
        row for row in layer_b['admissibility_gates'] if row['gate_id'] == 'POOLING_LEVEL'
    )
    comparisons = {row['field']: row['value'] for row in pooling_gate['comparisons']}
    if int(comparisons['maximum_pooling_depth']) != MAX_POOLING_DEPTH:
        raise PreflightError('the v2 maximum pooling depth drifted')
    if int(comparisons['maximum_level_for_a_reported_estimate_rank']) != MAX_POOLING_DEPTH:
        raise PreflightError('the v2 maximum reported estimate level rank drifted')
    if comparisons['exact_claim_requires_level'] != SUPPORT_LEVEL:
        raise PreflightError('the v2 exact claim level drifted')
    if (
        protocol['pooling_limits']['maximum_pooling_level_for_a_reported_estimate']
        != MAX_POOLING_LEVEL_FOR_ESTIMATE
    ):
        raise PreflightError('the v2 maximum reported estimate level drifted')
    if protocol['pooling_limits']['only_support_source_level'] != SUPPORT_LEVEL:
        raise PreflightError('the v2 only support source level must stay L0_EXACT_KEY')

    return {
        'protocol': protocol,
        'protocol_v2_byte_sha256': actual_byte_sha,
        'protocol_v2_canonical_payload_sha256': stable_hash(protocol),
        'layer_b': layer_b,
        'node_closure': closure,
        'calibration_thresholds': calibration_gate_thresholds(protocol),
        'amendment_id': protocol['amendments']['current_amendment_id'],
        'superseded_digest': protocol['amendments']['superseded_digest'],
    }


def _manifest_rows(tree: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Independent re-derivation of the frozen 38-node requirement manifest."""
    rows = []
    for node in tree['nodes']:
        edges = node.get('edges') or []
        rows.append({
            'id': node['id'],
            'path': ':'.join(node['path']),
            'runtime_support_context_key': node['runtime_support_context_key'],
            'audit_exact_key': node['audit_exact_key'],
            'runtime_exact_preflop_node_key': node['runtime_exact_preflop_node_key'],
            'actions': sorted({str(edge['action']) for edge in edges}),
            'edge_count': len(edges),
        })
    rows.sort(key=lambda row: row['path'])
    return rows


def load_pinned_inputs() -> dict[str, Any]:
    """Verify every consumed identity before a single exact key is resolved."""
    pinned = fit_tool.load_verified_inputs()
    tree = pinned['tree']

    protocol_bytes = PROTOCOL_PATH.read_bytes()
    actual_byte_sha = hashlib.sha256(protocol_bytes).hexdigest()
    if actual_byte_sha != PROTOCOL_BYTE_SHA256:
        raise PreflightError(f'frozen protocol byte hash drifted: {actual_byte_sha}')
    sidecar = PROTOCOL_DIGEST_PATH.read_text().split()[0]
    if sidecar != PROTOCOL_BYTE_SHA256:
        raise PreflightError('frozen protocol digest sidecar drifted')
    if PROTOCOL_COPY_PATH.read_bytes() != protocol_bytes:
        raise PreflightError('the content-addressed protocol copy differs from the frozen bytes')
    protocol = json.loads(protocol_bytes)
    if protocol.get('schema') != PROTOCOL_SCHEMA:
        raise PreflightError('unexpected frozen protocol schema')
    if protocol.get('status') != PROTOCOL_STATUS:
        raise PreflightError('the frozen protocol is not frozen before validation')
    if stable_hash(protocol) != PROTOCOL_CANONICAL_PAYLOAD_SHA256:
        raise PreflightError('frozen protocol canonical payload hash drifted')

    manifest = protocol['requirement_manifest']
    rows = _manifest_rows(tree)
    if rows != manifest['nodes']:
        raise PreflightError('frozen requirement manifest does not match the #388 tree')
    if stable_hash(rows) != manifest['manifest_canonical_sha256']:
        raise PreflightError('frozen requirement manifest digest drifted')
    if manifest['node_count'] != REQUIRED_NODE_COUNT or len(rows) != REQUIRED_NODE_COUNT:
        raise PreflightError('the frozen requirement manifest must pin 38 nodes')
    if manifest['unresolved_sizing_frontier_count'] != UNRESOLVED_FRONTIER_COUNT:
        raise PreflightError('the frozen requirement manifest frontier count drifted')
    if manifest['identity_granularity'] != 'hierarchical_exact_key':
        raise PreflightError('unexpected manifest identity granularity')

    thresholds = protocol['thresholds']
    if int(thresholds['minimum_marginal_observations']) != MIN_MARGINAL_OBSERVATIONS:
        raise PreflightError('frozen observation threshold drifted')
    if int(thresholds['minimum_distinct_hands']) != MIN_DISTINCT_HANDS:
        raise PreflightError('frozen distinct-hand threshold drifted')
    if thresholds['exact_claim_requires'] != (
        'L0_EXACT_KEY meeting both the 20-observation and 20-distinct-hands thresholds'
    ):
        raise PreflightError('unexpected frozen exact-claim rule')
    pooling = protocol['pooling_limits']
    if pooling['only_support_source_level'] != SUPPORT_LEVEL:
        raise PreflightError('the only support source level must stay L0_EXACT_KEY')
    if pooling['maximum_pooling_level_for_an_exact_support_claim'] != SUPPORT_LEVEL:
        raise PreflightError('an exact-support claim may only use L0_EXACT_KEY')

    rule = protocol['issue367_rule']
    if rule['authorized_at_freeze'] is not False:
        raise PreflightError('#367 must stay unauthorized at freeze time')
    if CANDIDATE_CANONICAL_SHA256 not in json.dumps(rule['authorized_when']):
        raise PreflightError('the frozen #367 rule does not name this candidate identity')
    if rule['hero_ev_consumed'] or rule['model_b_consumed']:
        raise PreflightError('the frozen rule must report no Hero EV and no Model B consumption')

    fit_index = fit_tool.verify_content_address(fit_tool.OUTPUT)
    candidate = _load(CANDIDATE_PATH)
    H.validate_candidate(candidate)
    candidate_sha = H.canonical_candidate_sha256(candidate)
    if candidate_sha != CANDIDATE_CANONICAL_SHA256:
        raise PreflightError(f'candidate canonical payload hash drifted: {candidate_sha}')
    if sha256_file(CANDIDATE_PATH) != CANDIDATE_BYTE_SHA256:
        raise PreflightError('candidate byte hash drifted')
    if fit_index['CANDIDATE.json']['canonical_payload_sha256'] != candidate_sha:
        raise PreflightError('candidate bytes are not the ones pinned by the fit index')
    identity = candidate['identity']
    if identity['candidate_id'] != H.CANDIDATE_ID:
        raise PreflightError('candidate contract id drifted')
    if identity['status'] != H.CANDIDATE_STATUS:
        raise PreflightError('candidate must stay candidate-only and inactive')
    if identity['source_report_hash'] != baseline_tool.ISSUE388_TRAIN_SUPPORT_SHA256:
        raise PreflightError('candidate support source is not the pinned #388 TRAIN support')
    for flag in (
        'nearest_price_fallback',
        'nearest_context_fallback',
        'representative_price_fallback',
    ):
        if candidate.get(flag) is not False:
            raise PreflightError(f'{flag} must stay forbidden in the provider contract')
    if candidate['schema'] != H.SCHEMA:
        raise PreflightError('unexpected provider likelihood schema')

    fixture = _load(FIXTURE_PATH)
    if fixture.get('scenario_id') != SCENARIO_ID:
        raise PreflightError('unexpected #321 canonical fixture')
    if sha256_file(FIXTURE_PATH) != tree['fixture_sha256']:
        raise PreflightError('canonical fixture hash does not match the required tree')
    snapshot_ids = [row['id'] for row in fixture['snapshots']]
    if 'before_hero' not in snapshot_ids:
        raise PreflightError('the canonical fixture lost its before_hero snapshot')
    root = next((node for node in tree['nodes'] if node['id'] == tree['root_id']), None)
    if root is None or list(root['path']) != ROOT_PATH:
        raise PreflightError('the required tree root is not SB:ISO@5')
    if float(tree['rules']['initial_iso_target_total_bb']) != INITIAL_ISO_TARGET_TOTAL_BB:
        raise PreflightError('the required tree initial ISO target drifted')
    if tree['rules']['nearest_price'] is not False or tree['rules']['nearest_context'] is not False:
        raise PreflightError('the required tree must forbid nearest-price/nearest-context')

    return {
        'pinned': pinned,
        'tree': tree,
        'protocol': protocol,
        'manifest': manifest,
        'manifest_rows': rows,
        'candidate': candidate,
        'candidate_sha': candidate_sha,
        'fit_index': fit_index,
        'fixture': fixture,
        'root': root,
        'protocol_byte_sha256': actual_byte_sha,
    }


def live_context(node: Mapping[str, Any]) -> dict[str, Any]:
    """Public context of a required node, rebuilt from its frozen stack bucket."""
    return fit_tool.reconstruct_node_context(node)


def resolve_exact(
    candidate: Mapping[str, Any], node: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Query the provider for one node's exact key; fail closed on any substitution."""
    context = live_context(node)
    legal = fit_tool.legal_actions(node)
    response = H.resolve_exact_context(candidate=candidate, context=context, legal_actions=legal)
    H.validate_response(response)
    H.assert_support_isolation(
        requested_key=response['requested_key'], source_key=response['support']['source_key']
    )
    if response['requested_key'] != node['audit_exact_key']:
        raise PreflightError('the resolved exact key is not the required node key')
    return context, response


def _gate(
    gate_id: str,
    *,
    applicable: bool,
    evaluated: bool,
    passed: bool,
    detail: str,
    evidence: Mapping[str, Any] | None = None,
    violation_reason_code: str | None = None,
) -> dict[str, Any]:
    return {
        'gate_id': gate_id,
        'reason_code': LAYER_B_GATE_REASON_CODE_BY_ID[gate_id],
        'applies_to_answer': bool(applicable),
        'evaluated': bool(evaluated),
        'passed': bool(passed),
        'violation_reason_code': violation_reason_code,
        'detail': detail,
        'evidence': dict(evidence or {}),
    }


def calibration_gate_decision(
    calibration_evidence: Mapping[str, Any] | None,
    thresholds: Mapping[str, Any],
) -> dict[str, Any]:
    """Evaluate the frozen CALIBRATION gate; missing evidence fails closed.

    The measured pooled ECE lives in the frozen VALIDATION result, which this
    TRAIN-only preflight never reads.  Absent explicit evidence the gate is
    ``evaluated: false`` and therefore refused -- an unevaluated layer-B gate may
    never close a node (``default_when_a_gate_is_unevaluated: false``).
    """
    maximum_ece = float(thresholds['maximum_absolute_ece'])
    maximum_delta = float(thresholds['maximum_ece_delta_vs_active'])
    minimum_bins = int(thresholds['minimum_bin_support_for_a_calibration_claim'])
    pinned = {
        'maximum_absolute_ece': maximum_ece,
        'maximum_ece_delta_vs_active': maximum_delta,
        'minimum_bin_support_for_a_calibration_claim': minimum_bins,
        'bins_per_action_class': int(thresholds['bins_per_action_class']),
        'report_pooling_level_always': bool(thresholds['report_pooling_level_always']),
    }
    if calibration_evidence is None:
        return {
            'evaluated': False,
            'passed': False,
            'detail': 'GATE_UNEVALUATED_PRE_VALIDATION',
            'thresholds': pinned,
            'evidence': {
                'source': CALIBRATION_EVIDENCE_SOURCE,
                'reason': (
                    'this preflight consumes no VALIDATION split, so the frozen absolute/relative '
                    'calibration gate has no measured evidence and stays open (fail closed)'
                ),
                'pooled_ece': None,
                'ece_delta_vs_active': None,
                'bins_meeting_minimum_support': None,
            },
        }
    pooled_ece = calibration_evidence.get('pooled_ece')
    delta = calibration_evidence.get('ece_delta_vs_active')
    bins = calibration_evidence.get('bins_meeting_minimum_support')
    checks = {
        'pooled_ece_within_maximum_absolute': (
            pooled_ece is not None and float(pooled_ece) <= maximum_ece
        ),
        'ece_delta_within_maximum_vs_active': (
            delta is not None and float(delta) <= maximum_delta
        ),
        'bins_meet_minimum_support': (bins is not None and int(bins) >= minimum_bins),
    }
    return {
        'evaluated': True,
        'passed': all(checks.values()),
        'detail': 'GATE_EVALUATED',
        'thresholds': pinned,
        'checks': checks,
        'evidence': {
            'source': str(calibration_evidence.get('source') or 'EXPLICIT_CALIBRATION_EVIDENCE'),
            'pooled_ece': None if pooled_ece is None else float(pooled_ece),
            'ece_delta_vs_active': None if delta is None else float(delta),
            'bins_meeting_minimum_support': None if bins is None else int(bins),
        },
    }


def layer_b_gate_report(
    response: Mapping[str, Any],
    *,
    calibration_evidence: Mapping[str, Any] | None = None,
    calibration_thresholds: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Machine-readable verdict for every frozen layer-B admissibility gate.

    ``RAISE_SIZING_FRONTIER`` is a property of the *branch*, so it is evaluated
    for every status (including ``EXACT_UNRESOLVED``).  The remaining gates are
    only applicable when an answer is emitted; for an unresolved node they are
    reported as not applicable instead of being counted as failures.
    """
    status = str(response['status'])
    answered = status != H.STATUS_EXACT_UNRESOLVED
    support = response['support']
    pooling = response.get('pooling')
    raise_sizing = response.get('raise_sizing') or {}
    uncertainty = response.get('uncertainty')
    posterior = response.get('posterior')
    requested_key = str(response['requested_key'])
    thresholds = dict(
        calibration_thresholds
        if calibration_thresholds is not None
        else {
            'maximum_absolute_ece': 0.05,
            'maximum_ece_delta_vs_active': 0.02,
            'minimum_bin_support_for_a_calibration_claim': MIN_DISTINCT_HANDS,
            'bins_per_action_class': 10,
            'report_pooling_level_always': True,
        }
    )

    # --- EXACT_KEY_IDENTITY -------------------------------------------------
    identity_checks = {
        'support_source_key_equals_requested_key': str(support['source_key']) == requested_key,
        'support_not_borrowed_from_other_keys': support['borrowed_from_other_keys'] is False,
        'support_isolation_rule_declared': (
            support['support_isolation_rule'] == H.SUPPORT_ISOLATION_RULE
        ),
    }
    retained_axes: list[str] = []
    pooled_axes: list[str] = []
    if isinstance(pooling, Mapping):
        retained_axes = list(pooling['retained_axes'])
        pooled_axes = list(pooling['pooled_axes'])
        identity_checks['never_mutualizable_axes_retained'] = (
            set(H.NEVER_MUTUALIZABLE_AXES) <= set(retained_axes)
        )
        identity_checks['never_mutualizable_axes_not_pooled'] = not (
            set(H.NEVER_MUTUALIZABLE_AXES) & set(pooled_axes)
        )
    identity_passed = all(identity_checks.values())
    gates: dict[str, Any] = {
        'EXACT_KEY_IDENTITY': _gate(
            'EXACT_KEY_IDENTITY',
            applicable=True,
            evaluated=True,
            passed=identity_passed,
            detail=(
                'support.source_key == requested_key, no cross-key borrowing and every '
                'never-mutualizable axis retained'
            ),
            violation_reason_code=None if identity_passed else H.SUPPORT_LAUNDERING_REASON,
            evidence={
                'requested_key': requested_key,
                'support_source_key': support['source_key'],
                'borrowed_from_other_keys': bool(support['borrowed_from_other_keys']),
                'never_mutualizable_axes': list(H.NEVER_MUTUALIZABLE_AXES),
                'retained_axes': retained_axes,
                'pooled_axes': pooled_axes,
                'checks': identity_checks,
            },
        ),
    }

    # --- POOLING_PROVENANCE (estimate answers only) -------------------------
    missing_provenance: list[str] = []
    provenance_checks: dict[str, bool] = {}
    if status == H.STATUS_EXACT_HIERARCHICAL_ESTIMATE:
        if not isinstance(pooling, Mapping):
            missing_provenance = list(POOLING_PROVENANCE_FIELDS)
        else:
            missing_provenance = [
                field for field in POOLING_PROVENANCE_FIELDS if pooling.get(field) is None
            ]
            provenance_checks['pooling_source_key_names_a_parent'] = (
                str(pooling['source_key']) != requested_key
            )
            provenance_checks['pooling_level_is_a_parent_level'] = (
                str(pooling['level']) != SUPPORT_LEVEL
            )
    gates['POOLING_PROVENANCE'] = _gate(
        'POOLING_PROVENANCE',
        applicable=(status == H.STATUS_EXACT_HIERARCHICAL_ESTIMATE),
        evaluated=True,
        passed=not missing_provenance and all(provenance_checks.values()),
        detail=(
            'an exact-context estimate reports the pooling level, its source key, its source counts '
            'and the retained/pooled axes, and pools toward a declared parent -- never toward itself'
        ),
        evidence={
            'required_fields': list(POOLING_PROVENANCE_FIELDS),
            'missing_fields': missing_provenance,
            'pooling_level_reported': bool(isinstance(pooling, Mapping)),
            'checks': provenance_checks,
        },
    )

    # --- POOLING_LEVEL ------------------------------------------------------
    level = str(pooling['level']) if isinstance(pooling, Mapping) else None
    level_rank = None
    if level in H.POOLING_LEVELS:
        level_rank = int(H.LEVEL_SPEC_BY_NAME[level]['rank'])
    if status == H.STATUS_EXACT_EMPIRICAL_STRONG:
        level_passed = level == SUPPORT_LEVEL
    elif answered:
        level_passed = bool(
            level in H.POOLING_LEVELS and level_rank is not None and level_rank <= MAX_POOLING_DEPTH
        )
    else:
        level_passed = False
    gates['POOLING_LEVEL'] = _gate(
        'POOLING_LEVEL',
        applicable=answered,
        evaluated=answered,
        passed=level_passed,
        detail=(
            'a declared pooling level, EXACT_EMPIRICAL_STRONG only at L0_EXACT_KEY and no reported '
            'estimate deeper than L4_POSITION_PRICE_PRIOR'
        ),
        evidence={
            'pooling_level': level,
            'pooling_level_rank': level_rank,
            'exact_claim_requires_level': SUPPORT_LEVEL,
            'maximum_level_for_a_reported_estimate': MAX_POOLING_LEVEL_FOR_ESTIMATE,
            'maximum_pooling_depth': MAX_POOLING_DEPTH,
        },
    )

    # --- EFFECTIVE_SAMPLE_SIZE ---------------------------------------------
    support_ess = float(support['effective_sample_size'])
    support_hands = int(support['distinct_hands'])
    support_observations = int(support['observations'])
    ess_checks = {
        'effective_sample_size_credited_at_hand_level': support_ess == float(support_hands),
    }
    if isinstance(pooling, Mapping):
        ess_checks['pooling_source_ess_credited_at_hand_level'] = (
            float(pooling['source_effective_sample_size'])
            == float(pooling['source_distinct_hands'])
        )
        ess_checks['effective_sample_size_not_inflated_by_pooling'] = (
            support_ess <= float(support_hands)
        )
        ess_checks['pooling_source_meets_minimum_thresholds'] = bool(
            int(pooling['source_observations']) >= MIN_MARGINAL_OBSERVATIONS
            and int(pooling['source_distinct_hands']) >= MIN_DISTINCT_HANDS
        )
    if status == H.STATUS_EXACT_EMPIRICAL_STRONG:
        ess_checks['exact_support_meets_minimum_thresholds'] = bool(
            support_observations >= MIN_MARGINAL_OBSERVATIONS
            and support_hands >= MIN_DISTINCT_HANDS
        )
    gates['EFFECTIVE_SAMPLE_SIZE'] = _gate(
        'EFFECTIVE_SAMPLE_SIZE',
        applicable=answered,
        evaluated=answered,
        passed=all(ess_checks.values()),
        detail=(
            'support.effective_sample_size is credited at the hand level, never inflated by pooling, '
            'and the level actually used meets the frozen 20/20 thresholds'
        ),
        evidence={
            'support_observations': support_observations,
            'support_distinct_hands': support_hands,
            'support_effective_sample_size': support_ess,
            'pooling_source_observations': (
                None if not isinstance(pooling, Mapping) else int(pooling['source_observations'])
            ),
            'pooling_source_distinct_hands': (
                None if not isinstance(pooling, Mapping) else int(pooling['source_distinct_hands'])
            ),
            'pooling_source_effective_sample_size': (
                None
                if not isinstance(pooling, Mapping)
                else float(pooling['source_effective_sample_size'])
            ),
            'checks': ess_checks,
        },
    )

    # --- UNCERTAINTY --------------------------------------------------------
    uncertainty_checks = {
        'posterior_reported': isinstance(posterior, Mapping) and bool(posterior),
        'uncertainty_reported': isinstance(uncertainty, Mapping) and bool(uncertainty),
    }
    if isinstance(posterior, Mapping) and isinstance(uncertainty, Mapping):
        uncertainty_checks['uncertainty_covers_every_reported_action'] = (
            set(posterior) == set(uncertainty.get('actions') or {})
        )
        uncertainty_checks['uncertainty_reports_the_level_actually_used'] = bool(
            uncertainty.get('level_used') == level
        )
    gates['UNCERTAINTY'] = _gate(
        'UNCERTAINTY',
        applicable=answered,
        evaluated=answered,
        passed=all(uncertainty_checks.values()),
        detail=(
            'the posterior and the uncertainty band are reported, cover every action and reflect the '
            'level actually used; an estimate is never shown without its pooling level'
        ),
        evidence={
            'posterior_present': isinstance(posterior, Mapping) and bool(posterior),
            'uncertainty_present': isinstance(uncertainty, Mapping) and bool(uncertainty),
            'uncertainty_level_used': (
                None if not isinstance(uncertainty, Mapping) else uncertainty.get('level_used')
            ),
            'pooling_level': level,
            'checks': uncertainty_checks,
        },
    )

    # --- CALIBRATION --------------------------------------------------------
    calibration = calibration_gate_decision(calibration_evidence, thresholds)
    calibration['gate_id'] = 'CALIBRATION'
    calibration['reason_code'] = LAYER_B_GATE_REASON_CODE_BY_ID['CALIBRATION']
    calibration['applies_to_answer'] = answered
    calibration['violation_reason_code'] = None
    calibration['evidence'] = {
        **calibration['evidence'],
        'reason_code': response.get('reason_code'),
        'pooling_level': level,
        'uncertainty_present': isinstance(uncertainty, Mapping) and bool(uncertainty),
    }
    gates['CALIBRATION'] = calibration

    # --- RAISE_SIZING_FRONTIER (branch property: every status) --------------
    raise_checks = {
        'unresolved_frontier_closes_the_node': False,
        'raise_sizing_resolved': not bool(raise_sizing.get('unresolved')),
        'state_is_not_an_unresolved_frontier': (
            str(raise_sizing.get('state')) != 'UNRESOLVED_SIZING_FRONTIER'
        ),
        'exact_support_only': bool(raise_sizing.get('exact_support_only')),
        'nearest_price_not_used': not bool(raise_sizing.get('nearest_price_used')),
        'representative_price_not_used': not bool(raise_sizing.get('representative_price_used')),
        'interpolation_not_used': not bool(raise_sizing.get('interpolation_used')),
    }
    raise_passed = all(
        value for key, value in raise_checks.items() if key != 'unresolved_frontier_closes_the_node'
    )
    gates['RAISE_SIZING_FRONTIER'] = _gate(
        'RAISE_SIZING_FRONTIER',
        applicable=True,
        evaluated=True,
        passed=raise_passed,
        detail=(
            'raise sizing is exact-support-only: a raise target is emitted only when the exact '
            'structural node supports it and no representative, nearest, interpolated, legal-minimum '
            'or pruned price fills an unresolved frontier'
        ),
        evidence={
            'raise_sizing_state': raise_sizing.get('state'),
            'supported_targets': list(raise_sizing.get('supported_targets') or []),
            'checks': raise_checks,
        },
    )
    return gates


def node_closure(
    response: Mapping[str, Any],
    *,
    calibration_evidence: Mapping[str, Any] | None = None,
    calibration_thresholds: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Protocol-v2 admissibility: empirical support *or* gated exact-context estimate.

    * ``EXACT_EMPIRICAL_STRONG`` closes on the unchanged layer-A definition
      (``L0_EXACT_KEY`` meeting both 20/20 thresholds, exact-key-only support).
    * ``EXACT_HIERARCHICAL_ESTIMATE`` closes if and only if every frozen layer-B
      gate passes; the counted support stays exact-key-only and pooling only
      feeds the prior, so an estimate is never counted as exact support.
    * ``EXACT_UNRESOLVED`` never closes.
    """
    gates = layer_b_gate_report(
        response,
        calibration_evidence=calibration_evidence,
        calibration_thresholds=calibration_thresholds,
    )
    status = str(response['status'])
    support = response['support']
    pooling = response.get('pooling')
    requested_key = str(response['requested_key'])
    observations = int(support['observations'])
    distinct_hands = int(support['distinct_hands'])

    identity_ok = gates['EXACT_KEY_IDENTITY']['passed'] is True
    thresholds_met = bool(
        observations >= MIN_MARGINAL_OBSERVATIONS and distinct_hands >= MIN_DISTINCT_HANDS
    )
    support_is_exact_key_only = bool(
        str(support['source_key']) == requested_key
        and support['borrowed_from_other_keys'] is False
        and support['support_isolation_rule'] == H.SUPPORT_ISOLATION_RULE
    )
    level = None if not isinstance(pooling, Mapping) else str(pooling['level'])
    pooling_only_parameters = bool(
        not isinstance(pooling, Mapping) or level != SUPPORT_LEVEL
    )

    empirical_closes = bool(
        status == H.STATUS_EXACT_EMPIRICAL_STRONG
        and level == SUPPORT_LEVEL
        and identity_ok
        and support_is_exact_key_only
        and thresholds_met
    )
    applicable_gates = [gate for gate in gates.values() if gate['applies_to_answer']]
    failed_gate_ids = [
        gate['gate_id'] for gate in applicable_gates if gate['evaluated'] and not gate['passed']
    ]
    unevaluated_gate_ids = [
        gate['gate_id'] for gate in applicable_gates if not gate['evaluated']
    ]
    estimate_closes = bool(
        status == H.STATUS_EXACT_HIERARCHICAL_ESTIMATE
        and identity_ok
        and support_is_exact_key_only
        and pooling_only_parameters
        and not failed_gate_ids
        and not unevaluated_gate_ids
    )
    closed = bool(empirical_closes or estimate_closes)

    # Reason codes explain an *open* node only: a closed node has nothing to
    # refuse, so a gate that is not consulted by its closure path (e.g. the
    # unevaluated calibration gate on the layer-A empirical path) is not a reason
    # code for it.
    reason_codes: list[str] = []
    if not closed:
        for gate_id in failed_gate_ids + unevaluated_gate_ids:
            code = LAYER_B_GATE_REASON_CODE_BY_ID[gate_id]
            if code not in reason_codes:
                reason_codes.append(code)
        unresolved_reason = response.get('unresolved_reason')
        if status == H.STATUS_EXACT_UNRESOLVED and unresolved_reason:
            if str(unresolved_reason) not in reason_codes:
                reason_codes.append(str(unresolved_reason))
        if not reason_codes:
            reason_codes.append('REFUSED_NODE_NOT_ADMISSIBLE')

    if closed:
        admissibility_class = 'EXACT_EMPIRICAL_STRONG' if empirical_closes else 'EXACT_HIERARCHICAL_ESTIMATE'
    else:
        admissibility_class = 'EXACT_UNRESOLVED'

    return {
        'rule_id': NODE_CLOSURE_RULE_ID,
        'status': status,
        'admissibility_class': admissibility_class,
        'closed': closed,
        'closes_the_node': closed,
        'counts_as_exact_support': bool(empirical_closes),
        'admissible_as_exact_context_estimate': bool(estimate_closes),
        'empirical_support_rule': (
            'LAYER_A_L0_EXACT_KEY_20_20_UNCHANGED (admissible_node_consumption_rule.admissible_when[0])'
        ),
        'estimate_rule': f'{NODE_CLOSURE_RULE_ID} (every frozen layer-B gate must pass)',
        'layer_b_gates_consulted_for_closure': bool(
            status == H.STATUS_EXACT_HIERARCHICAL_ESTIMATE
        ),
        'layer_b_gates': gates,
        'failed_gate_ids': failed_gate_ids,
        'unevaluated_gate_ids': unevaluated_gate_ids,
        'support_is_exact_key_only': support_is_exact_key_only,
        'pooling_only_feeds_parameters': pooling_only_parameters,
        'observations': observations,
        'distinct_hands': distinct_hands,
        'reason_codes': reason_codes,
        'posterior_present': response.get('posterior') is not None,
        'probability_emitted': response.get('posterior') is not None,
    }


def is_admissible(
    response: Mapping[str, Any],
    *,
    calibration_evidence: Mapping[str, Any] | None = None,
    calibration_thresholds: Mapping[str, Any] | None = None,
) -> bool:
    """True only when the node answer is admissible under protocol v2."""
    return bool(
        admissibility(
            response,
            calibration_evidence=calibration_evidence,
            calibration_thresholds=calibration_thresholds,
        )['closes_the_node']
    )


def admissibility(
    response: Mapping[str, Any],
    *,
    calibration_evidence: Mapping[str, Any] | None = None,
    calibration_thresholds: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """The structured protocol-v2 admissibility verdict for one node answer.

    The verdict names the admissibility *class* explicitly -- layer-A
    ``EXACT_EMPIRICAL_STRONG`` support, the layer-B gated
    ``EXACT_HIERARCHICAL_ESTIMATE``, or ``EXACT_UNRESOLVED`` -- together with the
    per-gate report, the refused gate reason codes and whether the answer may be
    counted as exact support.  ``is_admissible`` is the boolean view of it.
    """
    return node_closure(
        response,
        calibration_evidence=calibration_evidence,
        calibration_thresholds=calibration_thresholds,
    )


def support_record(response: Mapping[str, Any]) -> dict[str, Any]:
    support = response['support']
    return {
        'observations': int(support['observations']),
        'distinct_hands': int(support['distinct_hands']),
        'effective_sample_size': float(support['effective_sample_size']),
        'denominator': int(support['denominator']),
        'action_counts': dict(support['action_counts']),
        'source_key': support['source_key'],
        'support_isolation_rule': support['support_isolation_rule'],
        'borrowed_from_other_keys': bool(support['borrowed_from_other_keys']),
        'thresholds': {
            'minimum_marginal_observations': MIN_MARGINAL_OBSERVATIONS,
            'minimum_distinct_hands': MIN_DISTINCT_HANDS,
        },
        'meets_observation_threshold': int(support['observations']) >= MIN_MARGINAL_OBSERVATIONS,
        'meets_distinct_hand_threshold': int(support['distinct_hands']) >= MIN_DISTINCT_HANDS,
        'qualifies_as_exact_support': (
            int(support['observations']) >= MIN_MARGINAL_OBSERVATIONS
            and int(support['distinct_hands']) >= MIN_DISTINCT_HANDS
        ),
    }


def pooling_record(response: Mapping[str, Any]) -> dict[str, Any] | None:
    pooling = response['pooling']
    if pooling is None:
        return None
    return {
        'level': pooling['level'],
        'rank': int(pooling['rank']),
        'purpose': pooling['purpose'],
        'source_key': pooling['source_key'],
        'source_observations': int(pooling['source_observations']),
        'source_distinct_hands': int(pooling['source_distinct_hands']),
        'source_effective_sample_size': float(pooling['source_effective_sample_size']),
        'weight_exact': float(pooling['weight_exact']),
        'weight_parent': float(pooling['weight_parent']),
        'parent_dominated': bool(pooling['parent_dominated']),
        'retained_axes': list(pooling['retained_axes']),
        'pooled_axes': list(pooling['pooled_axes']),
        'kappa0': float(pooling['kappa0']),
        'alpha_per_legal_marginal_action': float(pooling['alpha_per_legal_marginal_action']),
        'support_source_key': pooling['support_source_key'],
        'support_isolation_rule': pooling['support_isolation_rule'],
        'counts_as_exact_support': pooling['level'] == SUPPORT_LEVEL,
    }


def pooling_diagnostics(response: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            'level': row['level'],
            'rank': int(row['rank']),
            'purpose': row['purpose'],
            'source_key': row['source_key'],
            'source_observations': int(row['source_observations']),
            'source_distinct_hands': int(row['source_distinct_hands']),
            'qualifies': bool(row['qualifies']),
            'support_source_allowed': bool(row['support_source_allowed']),
        }
        for row in response['pooling_diagnostics']
    ]


def uncertainty_record(response: Mapping[str, Any]) -> dict[str, Any] | None:
    uncertainty = response['uncertainty']
    if uncertainty is None:
        return None
    return {
        'method': uncertainty['method'],
        'level_used': uncertainty['level_used'],
        'confidence_level': float(uncertainty['confidence_level']),
        'level_effective_sample_size': float(uncertainty['level_effective_sample_size']),
        'actions': {
            action: {
                'mean': float(band['mean']),
                'lower': float(band['lower']),
                'upper': float(band['upper']),
                'half_width': float(band['half_width']),
            }
            for action, band in uncertainty['actions'].items()
        },
    }


def posterior_identity(response: Mapping[str, Any]) -> dict[str, Any]:
    posterior = response['posterior']
    return {
        'status': response['status'],
        'reason_code': response['reason_code'],
        'unresolved_reason': response.get('unresolved_reason'),
        'reason_detail': response.get('reason_detail'),
        'posterior': posterior,
        'posterior_sha256': None if posterior is None else H.canonical_sha256(posterior),
        'posterior_present': posterior is not None,
        'probability_emitted': posterior is not None,
        'response_sha256': H.canonical_sha256(response),
    }


def refusal(
    substitution_class: str,
    *,
    reason_code: str,
    detail: str,
    evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if substitution_class not in SUBSTITUTION_CLASSES:
        raise PreflightError(f'unknown substitution class: {substitution_class}')
    return {
        'substitution_class': substitution_class,
        'disposition': 'REFUSED_NOT_SUBSTITUTED',
        'applied': False,
        'reason_code': reason_code,
        'detail': detail,
        'evidence': dict(evidence or {}),
    }


def node_refusals(
    node: Mapping[str, Any],
    response: Mapping[str, Any],
    coarse_group: Mapping[str, Any] | None,
    tree_targets: Sequence[float],
) -> list[dict[str, Any]]:
    """Every nearest-* or borrowable substitution identified for this exact key."""
    raise_sizing = response['raise_sizing']
    requested_target = float(node['context']['target_total_bb'])
    return [
        refusal(
            'NEAREST_CONTEXT',
            reason_code='CROSS_KEY_SUPPORT_BORROWING_FORBIDDEN',
            detail=(
                'the runtime support-context key is parameters-only; a different key may never '
                'support this exact key, so the coarser context is recorded and never used'
            ),
            evidence={
                'coarse_level': 'L3_RUNTIME_SUPPORT_CONTEXT',
                'coarse_source_key': node['runtime_support_context_key'],
                'coarse_level_supports_exact_claim': False,
                'shared_required_nodes': list((coarse_group or {}).get('paths') or []),
                'distinct_exact_keys_in_group': int(
                    (coarse_group or {}).get('distinct_audit_exact_keys') or 1
                ),
                'used_as_support': False,
            },
        ),
        refusal(
            'NEAREST_PRICE',
            reason_code='EXACT_PRICE_ONLY_NO_NEAREST_PRICE',
            detail=(
                'the exact requested price is the only admissible key; an adjacent ISO target is '
                'never substituted for it'
            ),
            evidence={
                'requested_target_total_bb': requested_target,
                'frozen_iso_grid_adjacent_targets_refused': [
                    value
                    for value in ADJACENT_ISO_TARGETS_BB
                    if value != requested_target and requested_target == INITIAL_ISO_TARGET_TOTAL_BB
                ],
                'other_required_tree_targets': [
                    value for value in tree_targets if value != requested_target
                ],
                'observed_support_at_requested_price': int(response['support']['observations']),
                'used_as_support': False,
            },
        ),
        refusal(
            'REPRESENTATIVE_PRICE',
            reason_code='REPRESENTATIVE_PRICE_FORBIDDEN',
            detail='no representative or averaged raise price may stand in for the exact price',
            evidence={
                'provider_flag_representative_price_used': bool(
                    raise_sizing['representative_price_used']
                ),
                'used_as_support': False,
            },
        ),
        refusal(
            'LEGAL_MINIMUM_FALLBACK',
            reason_code='LEGAL_MINIMUM_FALLBACK_NOT_EXACT_SUPPORT',
            detail=(
                'a legal-minimum raise is not an exact supported target and never answers a frontier'
            ),
            evidence={
                'raise_sizing_state': raise_sizing['state'],
                'structured_supported_targets': list(raise_sizing['supported_targets']),
                'used_as_support': False,
            },
        ),
        refusal(
            'INTERPOLATED_PRICE',
            reason_code='INTERPOLATED_PRICE_FORBIDDEN',
            detail='no interpolated price between observations may answer the exact key',
            evidence={
                'provider_flag_interpolation_used': bool(raise_sizing['interpolation_used']),
                'used_as_support': False,
            },
        ),
        refusal(
            'CROSS_KEY_SUPPORT_BORROWING',
            reason_code='SUPPORT_ISOLATION_NO_KEY_BORROWS_SUPPORT',
            detail='support counts are exact and are never smoothed or borrowed across levels',
            evidence={
                'support_source_key': response['support']['source_key'],
                'requested_key': response['requested_key'],
                'source_equals_requested': (
                    response['support']['source_key'] == response['requested_key']
                ),
                'used_as_support': False,
            },
        ),
    ]


def node_record(
    index: int,
    node: Mapping[str, Any],
    manifest_node: Mapping[str, Any],
    response: Mapping[str, Any],
    coarse_group: Mapping[str, Any] | None,
    tree_targets: Sequence[float],
    *,
    calibration_evidence: Mapping[str, Any] | None = None,
    calibration_thresholds: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    raise_sizing = response['raise_sizing']
    legal = fit_tool.legal_actions(node)
    closure = node_closure(
        response,
        calibration_evidence=calibration_evidence,
        calibration_thresholds=calibration_thresholds,
    )
    return {
        'index': index,
        'exact_key': response['requested_key'],
        'exact_key_sha256': hashlib.sha256(response['requested_key'].encode()).hexdigest(),
        'node_identity': {
            'node_id': node['id'],
            'path': list(node['path']),
            'manifest_id': manifest_node['id'],
            'manifest_path': manifest_node['path'],
            'runtime_exact_preflop_node_key': node['runtime_exact_preflop_node_key'],
            'runtime_support_context_key': node['runtime_support_context_key'],
            'audit_exact_key': node['audit_exact_key'],
            'exact_key_matches_manifest': response['requested_key'] == manifest_node['audit_exact_key'],
            'exact_key_matches_required_tree': response['requested_key'] == node['audit_exact_key'],
            'identity_granularity': H.EXACT_GRANULARITY,
            'edge_count': int(manifest_node['edge_count']),
            'requires_raise_sizing': bool({'RAISE', 'JAM'} & set(legal)),
        },
        'public_context': dict(node['context']),
        'legal_actions': legal,
        'empirical_support': support_record(response),
        'pooling_provenance': pooling_record(response),
        'pooling_diagnostics': pooling_diagnostics(response),
        'uncertainty': uncertainty_record(response),
        'posterior_identity': posterior_identity(response),
        'node_closure': closure,
        'raise_sizing': {
            'policy': raise_sizing['policy'],
            'state': raise_sizing['state'],
            'unresolved': bool(raise_sizing['unresolved']),
            'supported_targets': list(raise_sizing['supported_targets']),
            'structural_node_key': raise_sizing['structural_node_key'],
            'exact_support_only': bool(raise_sizing['exact_support_only']),
            'nearest_price_used': bool(raise_sizing['nearest_price_used']),
            'representative_price_used': bool(raise_sizing['representative_price_used']),
            'interpolation_used': bool(raise_sizing['interpolation_used']),
        },
        'admissible_exact_answer': closure['closes_the_node'],
        'admissibility_class': closure['admissibility_class'],
        'counts_as_exact_support': closure['counts_as_exact_support'],
        'closure_reason_codes': list(closure['reason_codes']),
        'failed_layer_b_gate_ids': list(closure['failed_gate_ids']),
        'unevaluated_layer_b_gate_ids': list(closure['unevaluated_gate_ids']),
        'substitution_refusals': node_refusals(node, response, coarse_group, tree_targets),
    }


def coarse_merge_groups(tree: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Required-tree nodes collapsed by the coarser runtime support-context key."""
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for node in tree['nodes']:
        grouped.setdefault(node['runtime_support_context_key'], []).append(node)
    return {
        key: {
            'runtime_support_context_key': key,
            'node_ids': [node['id'] for node in nodes],
            'paths': [':'.join(node['path']) for node in nodes],
            'distinct_audit_exact_keys': len({node['audit_exact_key'] for node in nodes}),
        }
        for key, nodes in grouped.items()
    }


def sizing_frontier_records(
    tree: Mapping[str, Any], nodes: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    by_id = {node['id']: node for node in nodes}
    records = []
    for frontier in tree['unresolved_sizing_frontiers']:
        node = by_id.get(frontier['node_id'])
        if node is None:
            raise PreflightError('a sizing frontier points outside the required tree')
        records.append({
            'requested_key': node['audit_exact_key'],
            'runtime_support_context_key': node['runtime_support_context_key'],
            'runtime_exact_preflop_node_key': node['runtime_exact_preflop_node_key'],
            'node_id': node['id'],
            'path': list(node['path']),
            'action': frontier['action'],
            'legal_target_interval_bb': list(frontier['legal_target_interval_bb']),
            'reason': frontier['reason'],
            'descendants': frontier['descendants'],
            'expansion_rule': frontier['expansion_rule'],
        })
    return sorted(records, key=lambda record: record['path'])


def frontier_record(frontier: Mapping[str, Any], response: Mapping[str, Any]) -> dict[str, Any]:
    raise_sizing = response['raise_sizing']
    return {
        'exact_key': frontier['requested_key'],
        'requested_key': frontier['requested_key'],
        'node_id': frontier['node_id'],
        'path': list(frontier['path']),
        'runtime_support_context_key': frontier['runtime_support_context_key'],
        'runtime_exact_preflop_node_key': frontier['runtime_exact_preflop_node_key'],
        'action': frontier['action'],
        'legal_target_interval_bb': list(frontier['legal_target_interval_bb']),
        'node_reason': frontier['reason'],
        'exactly_supported_target_bb': None,
        'admitted_target_bb': None,
        'provider_raise_sizing_state': raise_sizing['state'],
        'provider_supported_targets': list(raise_sizing['supported_targets']),
        'descendant_closure': {
            'declared': frontier['descendants'],
            'expansion_rule': frontier['expansion_rule'],
            'enumerable_without_a_representative_price': False,
            'pruned_as_zero_mass': False,
        },
        'disposition': 'UNRESOLVED_FRONTIER_NOT_PRUNED',
        'substitution_refusals': [
            refusal(
                'NEAREST_PRICE',
                reason_code='EXACT_REFERENCE_RAISE_SIZING_UNAVAILABLE',
                detail='no adjacent or observed target may stand in for the exact raise target',
                evidence={
                    'legal_target_interval_bb': list(frontier['legal_target_interval_bb']),
                    'observed_targets_are_counts_only': True,
                    'used_as_support': False,
                },
            ),
            refusal(
                'REPRESENTATIVE_PRICE',
                reason_code='EXACT_REFERENCE_RAISE_SIZING_UNAVAILABLE',
                detail='a representative raise price would move the descendant public states',
                evidence={
                    'representative_price_used': bool(raise_sizing['representative_price_used'])
                },
            ),
            refusal(
                'LEGAL_MINIMUM_FALLBACK',
                reason_code='LEGAL_MIN_FALLBACK_NOT_EXACT_SUPPORT',
                detail='a legal-minimum raise is not an exact supported target',
                evidence={'legal_minimum_fallback_substituted': False},
            ),
            refusal(
                'INTERPOLATED_PRICE',
                reason_code='INTERPOLATED_PRICE_FORBIDDEN',
                detail='an interpolated price may not open the descendant closure',
                evidence={'interpolation_used': bool(raise_sizing['interpolation_used'])},
            ),
        ],
    }


def nearest_substitution_probes(
    candidate: Mapping[str, Any],
    node: Mapping[str, Any],
    response: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Executable key-separation probes: a touched price/context yields another key."""
    probes: list[dict[str, Any]] = []
    context = live_context(node)
    base_key = response['requested_key']
    base_support = int(response['support']['observations'])
    legal = fit_tool.legal_actions(node)

    for target in ADJACENT_ISO_TARGETS_BB:
        if target == float(context['target_total_bb']):
            continue
        delta = target - float(context['target_total_bb'])
        probe_context = dict(context)
        probe_context['target_total_bb'] = float(target)
        probe_context['to_call_bb'] = max(0.0, float(context['to_call_bb']) + delta)
        probe_context['pot_before_bb'] = max(0.0, float(context['pot_before_bb']) + delta)
        probe_key = H.hierarchical_exact_key(probe_context)
        probe_response = H.resolve_exact_context(
            candidate=candidate, context=probe_context, legal_actions=legal
        )
        H.validate_response(probe_response)
        H.assert_support_isolation(
            requested_key=probe_response['requested_key'],
            source_key=probe_response['support']['source_key'],
        )
        probe_support = int(probe_response['support']['observations'])
        probes.append({
            'substitution_class': 'NEAREST_PRICE',
            'probe_kind': 'PROBE_ONLY_KEY_SEPARATION_NOT_A_TRAIN_CONTEXT',
            'base_exact_key': base_key,
            'base_support_observations': base_support,
            'probe_target_total_bb': float(target),
            'probe_exact_key': probe_key,
            'probe_response_requested_key': probe_response['requested_key'],
            'probe_status': probe_response['status'],
            'probe_support_observations': probe_support,
            'keys_distinct': probe_key != base_key,
            'base_support_reused_for_probe': bool(
                probe_key != base_key and base_support > 0 and probe_support == base_support
            ),
            'disposition': 'REFUSED_NOT_SUBSTITUTED',
            'reason_code': 'EXACT_PRICE_ONLY_NO_NEAREST_PRICE',
        })

    base_whitelist = H.hierarchical_public_whitelist(context)
    context_probes = {
        'effective_stack_bucket': float(context['effective_stack_bb']) / 2.0,
        'pot_before_bb': float(context['pot_before_bb']) + 1.0,
    }
    for label, value in context_probes.items():
        probe_context = dict(context)
        if label == 'effective_stack_bucket':
            probe_context['effective_stack_bb'] = max(1.0, value)
        else:
            probe_context['pot_before_bb'] = value
        probe_whitelist = H.hierarchical_public_whitelist(probe_context)
        if probe_whitelist == base_whitelist:
            continue
        probe_key = H.hierarchical_exact_key_from_whitelist(probe_whitelist)
        probe_response = H.resolve_exact_context(
            candidate=candidate, context=probe_context, legal_actions=legal
        )
        H.validate_response(probe_response)
        H.assert_support_isolation(
            requested_key=probe_response['requested_key'],
            source_key=probe_response['support']['source_key'],
        )
        probe_support = int(probe_response['support']['observations'])
        probes.append({
            'substitution_class': 'NEAREST_CONTEXT',
            'probe_kind': 'PROBE_ONLY_KEY_SEPARATION_NOT_A_TRAIN_CONTEXT',
            'mutated_axis': label,
            'base_exact_key': base_key,
            'base_support_observations': base_support,
            'probe_exact_key': probe_key,
            'probe_response_requested_key': probe_response['requested_key'],
            'probe_status': probe_response['status'],
            'probe_support_observations': probe_support,
            'keys_distinct': probe_key != base_key,
            'base_support_reused_for_probe': bool(
                probe_key != base_key and base_support > 0 and probe_support == base_support
            ),
            'disposition': 'REFUSED_NOT_SUBSTITUTED',
            'reason_code': 'EXACT_CONTEXT_ONLY_NO_NEAREST_CONTEXT',
        })
    return probes


def required_tree_closure_report(
    *,
    closures: Sequence[Mapping[str, Any]],
    frontier_count: int,
    nodes_with_unresolved_raise_sizing: int,
    manifest_unresolved_frontier_count: int,
    tree_enumeration_complete: bool,
    manifest_tree_enumeration_complete: bool,
    substitutions_applied: int,
    key_separation_probes_passed: bool,
    hero_ev_executed: bool,
    recommendation_computed: bool,
    rollouts_executed: int,
    ev_values_computed: int,
) -> dict[str, Any]:
    """The protocol-v2 tree-closure conjunction, with a reason code per failure.

    ``required_tree_complete`` is true only when *every* required node is closed
    by an admissible answer -- ``EXACT_EMPIRICAL_STRONG`` at L0 with both 20/20
    thresholds, or ``EXACT_HIERARCHICAL_ESTIMATE`` with every frozen layer-B gate
    passing -- and no required branch keeps an unresolved raise-sizing frontier.
    This function is pure: it is driven by the per-node closures, so the
    fail-closed behaviour is testable without any provider call.
    """
    total_nodes = len(closures)
    closed_nodes = [closure for closure in closures if closure['closes_the_node']]
    open_nodes = [closure for closure in closures if not closure['closes_the_node']]
    open_reason_codes = sorted(
        {code for closure in open_nodes for code in closure['reason_codes']}
    )
    failed_gate_ids = sorted({gate for closure in closures for gate in closure['failed_gate_ids']})
    unevaluated_gate_ids = sorted(
        {gate for closure in closures for gate in closure['unevaluated_gate_ids']}
    )
    estimate_closures = [
        closure
        for closure in closed_nodes
        if closure['admissibility_class'] == 'EXACT_HIERARCHICAL_ESTIMATE'
    ]
    pooled_counted_as_exact = [
        closure
        for closure in closed_nodes
        if closure['admissibility_class'] == 'EXACT_HIERARCHICAL_ESTIMATE'
        and closure['counts_as_exact_support']
    ]

    every_node_closed = len(closed_nodes) == total_nodes and total_nodes > 0
    no_frontier = bool(
        frontier_count == 0
        and nodes_with_unresolved_raise_sizing == 0
        and manifest_unresolved_frontier_count == 0
    )
    fully_enumerated = bool(tree_enumeration_complete and manifest_tree_enumeration_complete)
    no_substitution = bool(substitutions_applied == 0 and key_separation_probes_passed)
    no_hero_ev = bool(
        hero_ev_executed is False
        and recommendation_computed is False
        and rollouts_executed == 0
        and ev_values_computed == 0
    )
    no_pooled_as_exact = not pooled_counted_as_exact

    conditions: dict[str, dict[str, Any]] = {
        'every_required_node_closed_by_an_admissible_answer': {
            'satisfied': bool(every_node_closed),
            'reason_code': None if every_node_closed else REFUSED_REQUIRED_NODE_OPEN,
            'reason_codes': [] if every_node_closed else open_reason_codes,
            'admissible_nodes': len(closed_nodes),
            'open_nodes': len(open_nodes),
            'total_nodes': total_nodes,
            'closed_as_exact_empirical_strong': sum(
                1 for closure in closed_nodes if closure['counts_as_exact_support']
            ),
            'closed_as_exact_hierarchical_estimate': len(estimate_closures),
            'failed_layer_b_gate_ids': failed_gate_ids,
            'unevaluated_layer_b_gate_ids': unevaluated_gate_ids,
            'rule': (
                'each required node must be admissible *and* pass every frozen gate: '
                'EXACT_EMPIRICAL_STRONG at L0_EXACT_KEY with both the 20-observation and '
                '20-distinct-hands thresholds met, or EXACT_HIERARCHICAL_ESTIMATE with every frozen '
                f'layer-B gate passing ({NODE_CLOSURE_RULE_ID})'
            ),
        },
        'no_unresolved_raise_sizing_frontier': {
            'satisfied': no_frontier,
            'reason_code': None if no_frontier else REFUSED_UNRESOLVED_RAISE_SIZING_FRONTIER,
            'reason_codes': [] if no_frontier else [REFUSED_UNRESOLVED_RAISE_SIZING_FRONTIER],
            'unresolved_frontiers': int(frontier_count),
            'nodes_with_unresolved_raise_sizing': int(nodes_with_unresolved_raise_sizing),
            'manifest_unresolved_frontier_count': int(manifest_unresolved_frontier_count),
            'rule': 'a RAISE frontier without an exactly supported target keeps the tree open',
        },
        'required_tree_fully_enumerated': {
            'satisfied': fully_enumerated,
            'reason_code': None if fully_enumerated else REFUSED_TREE_ENUMERATION_INCOMPLETE,
            'reason_codes': [] if fully_enumerated else [REFUSED_TREE_ENUMERATION_INCOMPLETE],
            'required_tree_enumeration_complete': bool(tree_enumeration_complete),
            'manifest_tree_enumeration_complete': bool(manifest_tree_enumeration_complete),
            'rule': 'the #388 enumeration must be complete, not only its node list',
        },
        'no_nearest_or_borrowed_substitution_applied': {
            'satisfied': no_substitution,
            'reason_code': None if no_substitution else REFUSED_SUBSTITUTION_APPLIED,
            'reason_codes': [] if no_substitution else [REFUSED_SUBSTITUTION_APPLIED],
            'substitutions_applied': int(substitutions_applied),
            'key_separation_probes_passed': bool(key_separation_probes_passed),
            'substitution_classes_refused': list(SUBSTITUTION_CLASSES),
            'rule': (
                'no nearest-price, nearest-context, representative, interpolated or borrowed support'
            ),
        },
        'no_hero_ev_or_recommendation_computed': {
            'satisfied': no_hero_ev,
            'reason_code': None if no_hero_ev else REFUSED_HERO_EV_OR_RECOMMENDATION,
            'reason_codes': [] if no_hero_ev else [REFUSED_HERO_EV_OR_RECOMMENDATION],
            'hero_ev_executed': bool(hero_ev_executed),
            'recommendation_computed': bool(recommendation_computed),
            'rollouts_executed': int(rollouts_executed),
            'ev_values_computed': int(ev_values_computed),
            'rule': 'the #367 real ISO EV runner is neither imported nor executed',
        },
        'no_pooled_estimate_is_counted_as_exact_support': {
            'satisfied': no_pooled_as_exact,
            'reason_code': None if no_pooled_as_exact else 'REFUSED_POOLED_SUPPORT_AS_EXACT',
            'reason_codes': [] if no_pooled_as_exact else ['REFUSED_POOLED_SUPPORT_AS_EXACT'],
            'pooled_closures_counted_as_exact_support': len(pooled_counted_as_exact),
            'rule': (
                'an exact-context estimate supplies parameters only and is never counted as exact '
                'support for the requested key'
            ),
        },
    }
    required_tree_complete = all(condition['satisfied'] for condition in conditions.values())
    reason_codes: list[str] = []
    for condition in conditions.values():
        if condition['reason_code'] and condition['reason_code'] not in reason_codes:
            reason_codes.append(condition['reason_code'])
        for code in condition['reason_codes']:
            if code not in reason_codes:
                reason_codes.append(code)
    for code in open_reason_codes:
        if code not in reason_codes:
            reason_codes.append(code)
    return {
        'rule_id': NODE_CLOSURE_RULE_ID,
        'required_tree_complete': bool(required_tree_complete),
        'reason_codes': sorted(reason_codes),
        'conditions': conditions,
        'admissible_nodes': len(closed_nodes),
        'open_nodes': len(open_nodes),
        'total_nodes': total_nodes,
        'open_node_reason_codes': open_reason_codes,
        'open_node_indices': [
            index
            for index, closure in enumerate(closures)
            if not closure['closes_the_node']
        ],
    }


def build() -> tuple[dict[str, Any], str]:
    holdout_scan = verify_no_holdout_access()
    hero_ev_scan = verify_no_hero_ev_execution()
    protected_before = protected_hashes()
    hero_ev_modules_before = set(hero_ev_modules_present())
    with hand_history_tripwire() as opened:
        v1_custody = verify_frozen_v1_preflight()
        protocol_v2 = load_frozen_v2_protocol()
        calibration_thresholds = protocol_v2['calibration_thresholds']
        inputs = load_pinned_inputs()
        tree = inputs['tree']
        candidate = inputs['candidate']
        manifest_nodes = inputs['manifest']['nodes']
        nodes = fit_tool.required_nodes(tree)
        groups = coarse_merge_groups(tree)
        tree_targets = sorted({float(node['context']['target_total_bb']) for node in tree['nodes']})

        records = []
        for index, node in enumerate(nodes):
            _, response = resolve_exact(candidate, node)
            records.append(
                node_record(
                    index,
                    node,
                    manifest_nodes[index],
                    response,
                    groups[node['runtime_support_context_key']],
                    tree_targets,
                    calibration_thresholds=calibration_thresholds,
                )
            )

        frontiers = []
        for frontier in sizing_frontier_records(tree, nodes):
            node = next(node for node in nodes if node['id'] == frontier['node_id'])
            _, response = resolve_exact(candidate, node)
            frontiers.append(frontier_record(frontier, response))

        _, root_response = resolve_exact(candidate, nodes[0])
        probes = nearest_substitution_probes(candidate, nodes[0], root_response)
    hero_ev_modules_during_build = sorted(
        set(hero_ev_modules_present()) - hero_ev_modules_before
    )
    if hero_ev_modules_during_build:
        raise PreflightError(
            f'Hero EV module imported while the preflight ran: {hero_ev_modules_during_build}'
        )
    hero_ev_scan['forbidden_modules_imported_during_build'] = []
    hero_ev_scan['runner_module_imported_by_preflight'] = False
    protected_after = protected_hashes()
    if protected_before != protected_after:
        raise PreflightError('an active registry, model or frozen protocol was mutated')

    admissible = [record for record in records if record['admissible_exact_answer']]
    unresolved_frontier_nodes = [
        record for record in records if record['raise_sizing']['state'] == 'UNRESOLVED_SIZING_FRONTIER'
    ]
    status_counts: dict[str, int] = {}
    reason_counts: dict[str, int] = {}
    for record in records:
        status = record['posterior_identity']['status']
        status_counts[status] = status_counts.get(status, 0) + 1
        reason = record['posterior_identity']['unresolved_reason'] or 'NONE'
        reason_counts[reason] = reason_counts.get(reason, 0) + 1

    substitutions_applied = 0
    key_separation_probes_passed = all(probe['keys_distinct'] for probe in probes)
    closure_report = required_tree_closure_report(
        closures=[record['node_closure'] for record in records],
        frontier_count=len(frontiers),
        nodes_with_unresolved_raise_sizing=len(unresolved_frontier_nodes),
        manifest_unresolved_frontier_count=int(
            inputs['manifest']['unresolved_sizing_frontier_count']
        ),
        tree_enumeration_complete=bool(tree['enumeration_complete']),
        manifest_tree_enumeration_complete=bool(inputs['manifest']['tree_enumeration_complete']),
        substitutions_applied=substitutions_applied,
        key_separation_probes_passed=key_separation_probes_passed,
        hero_ev_executed=False,
        recommendation_computed=False,
        rollouts_executed=0,
        ev_values_computed=0,
    )
    conditions = closure_report['conditions']
    required_tree_complete = closure_report['required_tree_complete']

    refusals_total = sum(len(record['substitution_refusals']) for record in records) + sum(
        len(frontier['substitution_refusals']) for frontier in frontiers
    )
    opened_inputs = sorted({str(path) for path in opened})
    hand_history_opens = sorted(path for path in opened_inputs if _is_hand_history_path(path))
    if hand_history_opens:
        raise PreflightError(f'hand-history opens recorded: {hand_history_opens}')

    root = inputs['root']
    preflight = {
        'schema': V2_SCHEMA,
        'supersedes_schema': SCHEMA,
        'issue': ISSUE,
        'source_issue': SOURCE_ISSUE,
        'scenario_issue': SCENARIO_ISSUE,
        'kind': 'EXACT_TREE_367_PREFLIGHT_NO_HERO_EV',
        'required_tree_complete': required_tree_complete,
        'required_tree_complete_reason_codes': list(closure_report['reason_codes']),
        'admissibility_protocol': {
            'revision': 'v2',
            'amendment_id': protocol_v2['amendment_id'],
            'node_closure_rule_id': NODE_CLOSURE_RULE_ID,
            'node_closure_value': NODE_CLOSURE_VALUE,
            'protocol_v2_schema': protocol_v2['protocol']['schema'],
            'protocol_v2_byte_sha256': protocol_v2['protocol_v2_byte_sha256'],
            'protocol_v2_canonical_payload_sha256': protocol_v2[
                'protocol_v2_canonical_payload_sha256'
            ],
            'layer_b_gate_ids': list(LAYER_B_GATE_IDS),
            'layer_b_gate_reason_codes': list(LAYER_B_GATE_REASON_CODES),
            'empirical_closure_rule': (
                'EXACT_EMPIRICAL_STRONG (layer A, unchanged): pooling.level == L0_EXACT_KEY, both '
                'the 20-observation and 20-distinct-hands thresholds met, support.source_key == '
                'requested_key and no support borrowed across keys'
            ),
            'estimate_closure_rule': (
                f'EXACT_HIERARCHICAL_ESTIMATE closes the node if and only if every frozen layer-B '
                f'gate passes ({NODE_CLOSURE_RULE_ID}); support stays exact-key-only and pooling '
                'only feeds the prior'
            ),
            'calibration_gate_status': (
                'UNEVALUATED_PRE_VALIDATION: this preflight consumes no VALIDATION split, so the '
                'frozen absolute/relative calibration gate has no measured evidence and fails '
                'closed (REFUSED_CALIBRATION, default_when_a_gate_is_unevaluated=false)'
            ),
            'calibration_thresholds': dict(protocol_v2['calibration_thresholds']),
            'no_gate_value_moved': True,
            'no_threshold_moved': True,
            'layer_b_gates_more_permissive_than_v1': False,
            'superseded_protocol_v2_digest': protocol_v2['superseded_digest'],
        },
        'key_contract': {
            'exact_key': 'hierarchical_exact_key == #388 audit_exact_key (L0_EXACT_KEY)',
            'runtime_support_context_key': 'support_context_key (L3_RUNTIME_SUPPORT_CONTEXT)',
            'runtime_exact_preflop_node_key': 'structural raise-sizing identity (MAPNODE_*)',
            'lookup': 'EXACT_STRING_EQUALITY_ONLY_NO_NEAREST',
            'fields': list(tree['key_contract']['audit_exact_key']['fields']),
            'audit_exact_key_role': tree['key_contract']['audit_exact_key']['role'],
        },
        'scenario': {
            'scenario_id': SCENARIO_ID,
            'fixture': _relative(FIXTURE_PATH),
            'fixture_sha256': sha256_file(FIXTURE_PATH),
            'root_path': list(ROOT_PATH),
            'root_id': tree['root_id'],
            'initial_iso_target_total_bb': INITIAL_ISO_TARGET_TOTAL_BB,
            'root_actor_position': root['context']['actor_position'],
            'root_family': root['context']['family'],
            'hero_position': 'SB',
        },
        'provider': {
            'name': H.SCHEMA,
            'entry_point': 'tools.preflop.model_a_sizing_hierarchical.resolve_exact_context',
            'candidate_id': H.CANDIDATE_ID,
            'candidate_instance_id': CANDIDATE_INSTANCE_ID,
            'candidate_canonical_payload_sha256': CANDIDATE_CANONICAL_SHA256,
            'candidate_byte_sha256': CANDIDATE_BYTE_SHA256,
            'identity_granularity': H.EXACT_GRANULARITY,
            'support_level': SUPPORT_LEVEL,
            'support_isolation_rule': H.SUPPORT_ISOLATION_RULE,
            'pooling_levels': list(H.POOLING_LEVELS),
            'thresholds': {
                'minimum_marginal_observations': MIN_MARGINAL_OBSERVATIONS,
                'minimum_distinct_hands': MIN_DISTINCT_HANDS,
                'kappa0': float(candidate['shrinkage']['kappa0']),
                'alpha_per_legal_marginal_action': float(
                    candidate['shrinkage']['alpha_per_legal_marginal_action']
                ),
            },
            'nearest_price_fallback': False,
            'nearest_context_fallback': False,
            'representative_price_fallback': False,
            'pooling_provenance_rule': (
                'pooling_provenance is null exactly when no admissible pooling level exists; the '
                'five per-level diagnostics are always recorded and an unresolved node emits no '
                'posterior and no uncertainty band'
            ),
            'exact_context_granularity': candidate['exact_context_granularity'],
            'admissibility_rule': NODE_CLOSURE_RULE_ID,
            'admissibility_protocol_revision': 'v2',
            'layer_b_gates_consulted_for_estimate_closure': list(LAYER_B_GATE_IDS),
            'layer_b_gates_consulted_for_empirical_closure': [],
            'authorized_for_367': False,
            'authorization_basis': (
                'FROZEN_VALIDATION_PROTOCOL.issue367_rule.authorized_at_freeze=false'
            ),
        },
        'required_tree': {
            'required_node_count': REQUIRED_NODE_COUNT,
            'manifest_node_count': int(inputs['manifest']['node_count']),
            'manifest_id': inputs['manifest']['manifest_id'],
            'manifest_canonical_sha256': inputs['manifest']['manifest_canonical_sha256'],
            'manifest_rederived_from_issue388': True,
            'manifest_matches_required_tree': inputs['manifest_rows'] == _manifest_rows(tree),
            'required_tree_sha256': baseline_tool.ISSUE388_REQUIRED_TREE_SHA256,
            'required_tree_byte_sha256': baseline_tool.ISSUE388_REQUIRED_TREE_BYTE_SHA256,
            'tree_enumeration_complete': bool(tree['enumeration_complete']),
            'unresolved_sizing_frontier_count': int(
                inputs['manifest']['unresolved_sizing_frontier_count']
            ),
            'distinct_exact_keys': len({record['exact_key'] for record in records}),
            'distinct_runtime_support_context_keys': len(
                {record['node_identity']['runtime_support_context_key'] for record in records}
            ),
            'runtime_keys_merging_exact_states': sum(
                1 for group in groups.values() if group['distinct_audit_exact_keys'] > 1
            ),
        },
        'nodes_queried': len(records),
        'sizing_frontiers_queried': len(frontiers),
        'nodes': records,
        'sizing_frontiers': frontiers,
        'nearest_substitution_audit': {
            'substitutions_applied': 0,
            'nearest_price_substitutions_applied': 0,
            'nearest_context_substitutions_applied': 0,
            'representative_price_substitutions_applied': 0,
            'interpolated_price_substitutions_applied': 0,
            'legal_minimum_substitutions_applied': 0,
            'cross_key_support_borrowings_applied': 0,
            'refusals_recorded': refusals_total,
            'refusal_classes': list(SUBSTITUTION_CLASSES),
            'key_separation_probes': probes,
            'key_separation_probes_passed': all(probe['keys_distinct'] for probe in probes),
            'support_source_equals_requested_key_for_every_node': all(
                record['empirical_support']['source_key'] == record['exact_key']
                for record in records
            ),
            'statement': (
                'every node is answered by exact string equality on its own requested key; adjacent '
                'prices, coarser contexts, representative/interpolated prices, legal-minimum raises '
                'and cross-key support borrowings are refused and traced'
            ),
        },
        'admissibility': {
            'conditions': conditions,
            'rule_id': NODE_CLOSURE_RULE_ID,
            'required_tree_complete': required_tree_complete,
            'required_tree_complete_reason_codes': list(closure_report['reason_codes']),
            'open_node_reason_codes': list(closure_report['open_node_reason_codes']),
            'open_node_indices': list(closure_report['open_node_indices']),
            'status_counts': status_counts,
            'unresolved_reason_counts': reason_counts,
            'admissibility_class_counts': {
                'EXACT_EMPIRICAL_STRONG': sum(
                    1 for record in records if record['admissibility_class'] == 'EXACT_EMPIRICAL_STRONG'
                ),
                'EXACT_HIERARCHICAL_ESTIMATE': sum(
                    1
                    for record in records
                    if record['admissibility_class'] == 'EXACT_HIERARCHICAL_ESTIMATE'
                ),
                'EXACT_UNRESOLVED': sum(
                    1 for record in records if record['admissibility_class'] == 'EXACT_UNRESOLVED'
                ),
            },
            'closed_as_exact_support_nodes': sum(
                1 for record in records if record['counts_as_exact_support']
            ),
            'admissible_exact_nodes': len(admissible),
            'blocked_nodes': len(records) - len(admissible),
            'blocked_node_paths': [
                record['node_identity']['path']
                for record in records
                if not record['admissible_exact_answer']
            ],
            'blocked_node_reason_codes': {
                ':'.join(record['node_identity']['path']): list(record['closure_reason_codes'])
                for record in records
                if not record['admissible_exact_answer']
            },
            'rule': (
                'required_tree_complete is true only when every required node is closed by an '
                'admissible answer and every frozen gate passes; otherwise it is false and carries '
                'reason codes. A fail-closed node is reported as EXACT_UNRESOLVED and is never '
                'repaired by lowering a frozen threshold'
            ),
        },
        'frozen_v1_preflight': v1_custody,
        'boundary': {
            'split_consumed': 'TRAIN',
            'validation_consumed': False,
            'test_consumed': False,
            'test_authorized': False,
            'test_decisions_read': 0,
            'dataset_archives_opened': False,
            'hand_histories_parsed': 0,
            'model_b_consumed': False,
            'hero_ev_executed': False,
            'recommendation_computed': False,
            'rollouts_executed': 0,
            'ev_values_computed': 0,
            'active_model_pointer_mutated': False,
            'ui_modified': False,
            'holdout_access_scan': holdout_scan,
            'hero_ev_scan': hero_ev_scan,
            'dataset_access_tripwire': {
                'check': 'pathlib_open_tripwire_during_build',
                'result': 'PASS',
                'opened_inputs': opened_inputs,
                'opened_input_count': len(opened_inputs),
                'hand_history_or_dataset_opens': [],
            },
            'issue367_authorization': {
                'authorized': False,
                'authorized_at_freeze': False,
                'basis': 'FROZEN_VALIDATION_PROTOCOL.issue367_rule',
                'consequence': (
                    'this preflight resolves provider keys only; no #367 real ISO EV run, no '
                    'exact-support grid extension and no provider wiring is performed'
                ),
            },
        },
        'protected_files_before_after_sha256': {
            'before': protected_before,
            'after': protected_after,
            'unchanged': protected_before == protected_after,
        },
        'evidence_bindings': {
            'protocol_byte_sha256': inputs['protocol_byte_sha256'],
            'protocol_canonical_payload_sha256': stable_hash(inputs['protocol']),
            'protocol_v2_byte_sha256': protocol_v2['protocol_v2_byte_sha256'],
            'protocol_v2_canonical_payload_sha256': protocol_v2[
                'protocol_v2_canonical_payload_sha256'
            ],
            'protocol_v2_amendment_id': protocol_v2['amendment_id'],
            'protocol_v2_revision_of': protocol_v2['protocol']['revision_of'],
            'protocol_digest_sidecar_sha256': PROTOCOL_DIGEST_PATH.read_text().split()[0],
            'protocol_copy_byte_sha256': hashlib.sha256(PROTOCOL_COPY_PATH.read_bytes()).hexdigest(),
            'protocol_status': inputs['protocol']['status'],
            'protocol_frozen_at': inputs['protocol']['frozen_at'],
            'candidate_canonical_payload_sha256': inputs['candidate_sha'],
            'candidate_byte_sha256': sha256_file(CANDIDATE_PATH),
            'fit_report_sha256': inputs['fit_index'][fit_tool.REPORT_NAME]['sha256'],
            'fit_report_canonical_payload_sha256': inputs['fit_index'][fit_tool.REPORT_NAME][
                'canonical_payload_sha256'
            ],
            'candidate_manifest_sha256': inputs['fit_index'][fit_tool.MANIFEST_NAME]['sha256'],
            'required_tree_sha256': baseline_tool.ISSUE388_REQUIRED_TREE_SHA256,
            'required_tree_byte_sha256': baseline_tool.ISSUE388_REQUIRED_TREE_BYTE_SHA256,
            'train_support_sha256': baseline_tool.ISSUE388_TRAIN_SUPPORT_SHA256,
            'train_support_byte_sha256': baseline_tool.ISSUE388_TRAIN_SUPPORT_BYTE_SHA256,
            'feasibility_decision_sha256': baseline_tool.ISSUE388_DECISION_SHA256,
            'feasibility_decision_byte_sha256': baseline_tool.ISSUE388_DECISION_BYTE_SHA256,
            'feasibility_decision': inputs['pinned']['issue388']['decision']['decision'],
            'feasibility_status': inputs['pinned']['issue388']['decision']['status'],
            'sparsity_baseline_canonical_payload_sha256': stable_hash(inputs['pinned']['baseline']),
            'hierarchy_spec_canonical_payload_sha256': stable_hash(inputs['pinned']['spec']),
            'canonical_fixture_sha256': sha256_file(FIXTURE_PATH),
            'active_reference_sha256': sha256_file(
                ROOT / 'training/models/preflop_population_model_v5.json'
            ),
        },
        'code': {
            'preflight_tool': {'path': _relative(SOURCE_PATH), 'sha256': sha256_file(SOURCE_PATH)},
            'provider': {
                'path': _relative(Path(H.__file__)),
                'sha256': sha256_file(Path(H.__file__)),
                'role': 'CANDIDATE_MODEL',
            },
            'node_context_reconstruction': {
                'path': _relative(Path(fit_tool.__file__)),
                'sha256': sha256_file(Path(fit_tool.__file__)),
                'role': 'CANDIDATE_FIT_TOOL',
            },
            'required_tree_tool': {
                'path': _relative(Path(baseline_tool.legacy.__file__)),
                'sha256': sha256_file(Path(baseline_tool.legacy.__file__)),
                'role': 'REQUIRED_TREE_TOOL',
            },
            'sparsity_baseline_tool': {
                'path': _relative(Path(baseline_tool.__file__)),
                'sha256': sha256_file(Path(baseline_tool.__file__)),
                'role': 'SPARSITY_BASELINE_TOOL',
            },
            'protocol_v2': {
                'path': _relative(PROTOCOL_V2_PATH),
                'sha256': sha256_file(PROTOCOL_V2_PATH),
                'role': 'FROZEN_PROTOCOL_V2_ADMISSIBILITY_GATES',
            },
        },
        'reproduction': {
            'command': 'python3 tools/simulation/issue419_exact_tree_preflight.py',
            'check_command': 'python3 tools/simulation/issue419_exact_tree_preflight.py --check',
            'bundle': _relative(V2_OUTPUT),
            'frozen_v1_bundle': _relative(OUTPUT),
            'frozen_v1_bundle_rewritten': False,
            'hero_ev_runner': 'tools/simulation/run_issue367_real_iso_ev.py',
            'hero_ev_runner_invoked': False,
            'deterministic': True,
            'stochastic_draws': 0,
        },
    }
    summary = render_summary(preflight)
    return {V2_NAME: preflight, SUMMARY_NAME: summary}, summary


def render_summary(preflight: Mapping[str, Any]) -> str:
    conditions = preflight['admissibility']['conditions']
    admissible = preflight['admissibility']['admissible_exact_nodes']
    total = preflight['nodes_queried']
    reason_codes = preflight['required_tree_complete_reason_codes']
    lines = [
        '# #419 - exact-tree #367 preflight v2 (no Hero EV)',
        '',
        f"Required nodes walked: **{total}**; sizing frontiers walked: "
        f"**{preflight['sizing_frontiers_queried']}**. Every node was answered by exact string "
        'equality on its own exact key (`hierarchical_exact_key`, byte-identical to the #388 '
        '`audit_exact_key`).',
        '',
        f"`required_tree_complete = {str(preflight['required_tree_complete']).lower()}` - "
        f"{admissible} of {total} required nodes are closed by an admissible answer. A node is "
        'admissible either as `EXACT_EMPIRICAL_STRONG` (layer A: `L0_EXACT_KEY` with both the '
        '20-observation and 20-distinct-hands thresholds met, exact-key support only) or as '
        '`EXACT_HIERARCHICAL_ESTIMATE` with every frozen layer-B gate passing '
        f"(`{preflight['admissibility_protocol']['node_closure_rule_id']}`).",
        '',
    ]
    for name, condition in conditions.items():
        verdict = 'satisfied' if condition['satisfied'] else 'NOT satisfied'
        suffix = ''
        if not condition['satisfied'] and condition['reason_code']:
            suffix = f" (`{condition['reason_code']}`)"
        lines.append(f'- `{name}`: {verdict}{suffix}')
    lines += [
        '',
        'Tree-closure reason codes: '
        + (', '.join(f'`{code}`' for code in reason_codes) if reason_codes else 'none')
        + '.',
        '',
        'Status counts over the 38 nodes: '
        + ', '.join(
            f"`{status}`={count}"
            for status, count in sorted(preflight['admissibility']['status_counts'].items())
        )
        + '.',
        '',
        'Admissibility classes: '
        + ', '.join(
            f"`{name}`={count}"
            for name, count in sorted(
                preflight['admissibility']['admissibility_class_counts'].items()
            )
        )
        + '.',
        '',
        'Abstention reasons: '
        + ', '.join(
            f"`{reason}`={count}"
            for reason, count in sorted(
                preflight['admissibility']['unresolved_reason_counts'].items()
            )
        )
        + '.',
        '',
        'Layer-B calibration gate: '
        f"{preflight['admissibility_protocol']['calibration_gate_status']}.",
        '',
        'No nearest-price, nearest-context, representative-price, interpolated-price, legal-minimum '
        'or cross-key-support substitution was applied: '
        f"{preflight['nearest_substitution_audit']['refusals_recorded']} refusals were recorded and "
        f"{len(preflight['nearest_substitution_audit']['key_separation_probes'])} executable "
        'key-separation probes confirmed that a changed price or context yields a different exact '
        "key instead of another key's support.",
        '',
        'The #367 Hero EV runner was neither imported nor executed '
        '(`hero_ev_executed=false`, `recommendation_computed=false`, `rollouts_executed=0`, '
        '`ev_values_computed=0`). VALIDATION and TEST stay unconsumed '
        '(`split_consumed=TRAIN`, `validation_consumed=false`, `test_consumed=false`), no hand '
        'history was opened, and no active registry, model pointer or frozen protocol byte changed '
        'before/after.',
        '',
        f"Provider: `{preflight['provider']['entry_point']}` bound to candidate "
        f"`{preflight['provider']['candidate_id']}` "
        f"(`{preflight['provider']['candidate_canonical_payload_sha256']}`), not authorized for "
        '#367 consumption at freeze time.',
        '',
        f"Frozen protocol: `{preflight['evidence_bindings']['protocol_byte_sha256']}`; required tree: "
        f"`{preflight['evidence_bindings']['required_tree_sha256']}`. Frozen protocol v2 (amendment "
        f"`{preflight['evidence_bindings']['protocol_v2_amendment_id']}`): "
        f"`{preflight['evidence_bindings']['protocol_v2_byte_sha256']}`.",
        '',
        'The superseded v1 preflight bundle '
        f"(`{preflight['frozen_v1_preflight']['bundle']}`) is re-verified byte-for-byte and never "
        'rewritten.',
        '',
        'Reproduce: `python3 tools/simulation/issue419_exact_tree_preflight.py`; verify: '
        '`python3 tools/simulation/issue419_exact_tree_preflight.py --check`. '
        'This preflight records evidence only; it admits nothing.',
        '',
    ]
    return '\n'.join(lines)


def persist(artifacts: Mapping[str, Any]) -> dict[str, Any]:
    V2_OUTPUT.mkdir(parents=True, exist_ok=True)
    objects = V2_OUTPUT / 'sha256'
    objects.mkdir(exist_ok=True)
    index: dict[str, Any] = {}
    referenced: set[str] = set()
    for name, value in artifacts.items():
        markdown = name.endswith('.md')
        data = str(value).encode() if markdown else serialize(value)
        extension = '.md' if markdown else '.json'
        digest = hashlib.sha256(data).hexdigest()
        entry = {'sha256': digest, 'object': 'sha256/' + digest + extension}
        if not markdown:
            entry['canonical_payload_sha256'] = stable_hash(value)
        index[name] = entry
        (V2_OUTPUT / name).write_bytes(data)
        (objects / (digest + extension)).write_bytes(data)
        referenced.add(digest + extension)
    (V2_OUTPUT / INDEX_NAME).write_text(json.dumps(index, sort_keys=True, indent=2) + '\n')
    for path in objects.iterdir():
        if path.is_file() and path.name not in referenced:
            path.unlink()
    return index


def check() -> int:
    custody = verify_frozen_v1_preflight()
    artifacts, _summary = build()
    problems: list[str] = []
    for name, value in artifacts.items():
        expected = str(value).encode() if name.endswith('.md') else serialize(value)
        if (V2_OUTPUT / name).read_bytes() != expected:
            problems.append(f'{name} differs from a fresh preflight')
    index = _load(V2_OUTPUT / INDEX_NAME)
    for name, entry in index.items():
        data = (V2_OUTPUT / name).read_bytes()
        if hashlib.sha256(data).hexdigest() != entry['sha256']:
            problems.append(f'{name} byte hash does not match {INDEX_NAME}')
        if data != (V2_OUTPUT / entry['object']).read_bytes():
            problems.append(f'{name} content-addressed copy mismatch')
    if problems:
        for problem in problems:
            print(problem, file=sys.stderr)
        return 1
    print(json.dumps({
        'schema': V2_SCHEMA,
        'check': 'PASS',
        'bundle': _relative(V2_OUTPUT),
        'artifacts': sorted(index),
        'frozen_v1_preflight': custody['artifacts'],
    }, indent=2))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--check',
        action='store_true',
        help='verify the persisted preflight bundle instead of rewriting it',
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.check:
        return check()
    artifacts, _summary = build()
    index = persist(artifacts)
    preflight = artifacts[V2_NAME]
    print(json.dumps({
        'schema': V2_SCHEMA,
        'bundle': _relative(V2_OUTPUT),
        'required_tree_complete': preflight['required_tree_complete'],
        'required_tree_complete_reason_codes': preflight[
            'required_tree_complete_reason_codes'
        ],
        'nodes_queried': preflight['nodes_queried'],
        'sizing_frontiers_queried': preflight['sizing_frontiers_queried'],
        'admissible_exact_nodes': preflight['admissibility']['admissible_exact_nodes'],
        'admissibility_class_counts': preflight['admissibility']['admissibility_class_counts'],
        'status_counts': preflight['admissibility']['status_counts'],
        'refusals_recorded': preflight['nearest_substitution_audit']['refusals_recorded'],
        'hero_ev_executed': preflight['boundary']['hero_ev_executed'],
        'validation_consumed': preflight['boundary']['validation_consumed'],
        'test_consumed': preflight['boundary']['test_consumed'],
        'frozen_v1_preflight_sha256': preflight['frozen_v1_preflight']['artifacts'][NAME],
        'artifact_sha256': index[V2_NAME]['sha256'],
    }, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

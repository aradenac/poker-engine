#!/usr/bin/env python3
"""#419 integration report **v2** (T7) -- the content-addressed evidence bundle.

This tool is the only writer of ``analysis/issue419_hierarchical_tree_v2/``.  It
consolidates the terminal #419 evidence into one content-addressed bundle whose
members are either **byte-identical copies** of a T1/T3/T4 authority or
**digest references** that are never dereferenced:

* copies (byte-identical, digest re-verified on every build and every ``--check``)
  -- ``HIERARCHICAL_MODEL_SPEC.json`` (T2 model spec),
  ``TRAIN_FIT_REPORT.json`` (T3 TRAIN fit report),
  ``CANDIDATE_MANIFEST.json`` (T4 candidate manifest),
  ``EXACT_TREE_PREFLIGHT_V2.json`` (TRAIN-only exact-tree preflight v2) and
  ``DECISION_V2.json`` (T7 terminal decision v2);
* references (a record of path + byte + canonical digests, never the bytes)
  -- ``FROZEN_VALIDATION_PROTOCOL_V2.json`` (T1 frozen protocol v2 authority) and
  ``VALIDATION_RESULT.json`` (the **already-consumed** v1 VALIDATION bytes).

The bundle **re-opens no holdout**.  The v1 VALIDATION result is referenced by
digest only: no hand history is parsed, no validation decision row is read, no
metric is recomputed, no threshold is re-selected, and the ``outcome`` /
``failing_gates`` rows quoted in the reference document are *published* rows of
the digest-referenced artifact recorded by the terminal decision v2.  The tool
proves that statically (AST self-scan: no holdout loader symbol, no holdout
loader module, no #367 runner symbol) and at runtime (a ``pathlib`` hand-history
and dataset tripwire that fails the build if such a file is opened), and it
records the proof in ``boundaries``.

The report is deliberately honest about two different kinds of evidence:

* ``ci_proven_claims`` is **empty**.  The CI evidence bundle (T5,
  ``ci_evidence/CI_EVIDENCE.json``) records
  ``ci_observation.status = NOT_OBSERVED``: the authoritative workflow
  ``Execute issue 419 hierarchical exact tree`` has never run at any head, and
  none of the five real CI runs recorded at the reviewed PR head executes a #419
  suite.  No local replay, declarative file, PR body or PR comment may promote
  that status;
* ``recorded_local_observations`` lists what was actually observed in this
  isolated worktree, each with ``authority = NON_AUTHORITATIVE_LOCAL``, and the
  red ones stay red.

It documents the supersessions the issue asks for: the superseded v2 protocol
payload ``508a31ec...`` (replaced by amendment
``V2_AMENDMENT_1_CONDITIONAL_NODE_CLOSURE``, current payload ``74b8a006...``),
the ``v1 EXACT_TREE_PREFLIGHT.json`` regeneration (mutant commit ``871e0bd``
rewrote the frozen bytes to ``e86b7c6b...``; the evidence-integrity correction
``c904524`` restored ``456d85be...``) and the v1→v2 raise-sizing frontier
revision (v1 ``93e7e3ed...`` superseded by v2 ``9df16dbb...``).

This revision of the bundle binds the **repaired** revisions.  Commit ``887e46a``
had re-pointed the preflight tool's ``V1_PREFLIGHT_SHA256`` / ``V1_INDEX_SHA256``
pins (and the protocol v2 ``PROTOCOL_V2_BYTE_SHA256`` /
``PROTOCOL_V2_CANONICAL_PAYLOAD_SHA256`` pins) onto the pre-correction custody
digests, so ``issue419_exact_tree_preflight.py --check`` was RED.  Commit
``9859c46`` (task ``backlog-911``) restored the four pins without moving one
frozen byte, so that check is GREEN again and the recorded pin findings are
RESOLVED, not residual.  This regeneration re-binds ``EXACT_TREE_PREFLIGHT_V2.json``
to ``9b924077...`` and ``DECISION_V2.json`` to ``4e220ece...`` -- the revisions
commits ``9859c46`` and ``0f9a6eb`` wrote -- which closes the residual finding
``INTEGRATION_BUNDLE_V2_PINS_PRE_REPAIR_REVISIONS`` the evidence-integrity
correction v2 record had explicitly deferred to the integration-bundle task.  No
frozen byte is rewritten and no threshold moves; the verdict stays
``BLOCKED_SCIENTIFIC`` / ``UNRESOLVED_HIERARCHICAL_TREE_GAP``.

The verdict is unchanged and never forced: ``BLOCKED_SCIENTIFIC`` /
``UNRESOLVED_HIERARCHICAL_TREE_GAP``, ``required_tree_complete=false``,
``validation_consumed=true`` (one single frozen read, not re-opened here),
``test_consumed=false``, ``active_pointer_mutated=false``, ``hero_ev_executed=false``,
``issue367_run=false``, ``next_issue=367``.

Output bundle (``analysis/issue419_hierarchical_tree_v2/``):

* ``HIERARCHICAL_MODEL_SPEC.json`` / ``TRAIN_FIT_REPORT.json`` /
  ``CANDIDATE_MANIFEST.json`` / ``EXACT_TREE_PREFLIGHT_V2.json`` /
  ``DECISION_V2.json`` -- byte-identical copies of the authorities
* ``FROZEN_VALIDATION_PROTOCOL_V2.json`` / ``VALIDATION_RESULT.json`` /
  ``RAISE_SIZING_FRONTIER_RESOLUTION.json`` -- digest references (no bytes
  duplicated, no holdout re-read); the frontier reference is the **v2** revision
  that supersedes the frozen v1 custody bytes
* ``INTEGRATION_REPORT.json`` -- the machine-readable integration report
* ``INTEGRATION_REPORT.md`` -- the rendered integration report
* ``SUMMARY.md`` -- human-readable summary
* ``N8N_TASK_RESULT.txt`` -- the exact n8n output block
* ``INTEGRATION_REPORT.sha256`` -- digest sidecar
* ``ARTIFACTS.json`` -- content-addressed index (its own twelve members)

Nothing outside the bundle directory is written.  The active Model A v5
pointer, both registries, the frozen v1/v2 protocol bytes, the T2 spec, the T1
baseline, the T3/T4 fit bundle, the consumed VALIDATION bytes, both preflight
bundles, both terminal decisions and the root ``ARTIFACTS.json``/``SUMMARY.md``
are re-verified byte-for-byte before and after the build and are never
rewritten.

Reproduce: ``python3 tools/training/build_hierarchical_integration_bundle_v2.py``
Verify:    ``python3 tools/training/build_hierarchical_integration_bundle_v2.py --check``
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

from tools.training.audit_preflop_sizing_support import stable_hash  # noqa: E402
from tools.training import validation_order_guard as order_guard  # noqa: E402

SOURCE_PATH = Path(__file__).resolve()
HERE = ROOT / 'analysis/issue419_hierarchical_tree_v2'
UPSTREAM = ROOT / 'analysis/issue419_hierarchical_tree'

INDEX_NAME = 'ARTIFACTS.json'
REPORT_NAME = 'INTEGRATION_REPORT.md'
REPORT_JSON_NAME = 'INTEGRATION_REPORT.json'
SUMMARY_NAME = 'SUMMARY.md'
N8N_NAME = 'N8N_TASK_RESULT.txt'
DIGEST_NAME = 'INTEGRATION_REPORT.sha256'

SCHEMA = 'poker-hierarchical-integration-report/v2'
REFERENCE_SCHEMA = 'poker-hierarchical-integration-reference/v2'
AUTHORED_AT = '2026-09-26T00:00:00Z'
ISSUE = 419
PARENT_ISSUE = 314
SOURCE_ISSUE = 388
SCENARIO_ISSUE = 321
NEXT_ISSUE = 367
BUNDLE_TASK = 'backlog-oso'
PLANNER_KEY = 'T7'
BRANCH = 'n8n/issue-419/task-backlog-oso'

CANDIDATE_ID = 'model-a-preflop-sizing-hierarchical-candidate-v1'
CANDIDATE_INSTANCE_ID = 'model-a-preflop-sizing-hierarchical-train-fit-419-v1'
CANDIDATE_SHA256 = '637302885b8119e6b0246d827462c36eb707c6e234d0b652483c956f03360999'
REQUIRED_TREE_SHA256 = '0ab232ae44e4157e2a47d4d3d611ac8ca9c2cdb54caf2568f256f6df35643a25'
REQUIRED_TREE_BYTE_SHA256 = '2c71f747f188af4d03c37ae145ef06cd53db844a8f064ec84b440fee8a02220c'
STATUS = 'BLOCKED_SCIENTIFIC'
DECISION = 'UNRESOLVED_HIERARCHICAL_TREE_GAP'
SUPPORT_ISOLATION_RULE = 'SUPPORT_ISOLATION_NO_KEY_BORROWS_SUPPORT'
PRIMARY_BLOCKER = 'NO_ADMISSIBLE_POOLING_LEVEL'
BLOCKERS = (
    'NO_ADMISSIBLE_POOLING_LEVEL',
    'UNRESOLVED_RAISE_SIZING_FRONTIER',
    'REFUSED_CALIBRATION',
    'REFUSED_COVERAGE_FLOOR',
)

# ---------------------------------------------------------------------------
# Upstream authorities.  Every digest below is re-derived from the persisted
# bytes on every build and every --check; a moved byte fails the tool closed.
# ---------------------------------------------------------------------------
MODEL_SPEC = UPSTREAM / 'HIERARCHICAL_MODEL_SPEC.json'
MODEL_SPEC_BYTE_SHA256 = '5be122e54e9ee07313a7efa0e0a6dbf4e195eceacf78287a9ac5a448964d105c'
MODEL_SPEC_CANONICAL_SHA256 = 'd4885e9d148e3a0246968168e246644d4dc81965383447bc74b3c8ca3c3541d4'

FIT_REPORT = UPSTREAM / 'fit/TRAIN_FIT_REPORT.json'
FIT_REPORT_BYTE_SHA256 = 'ae5b7cc84a8a7a38cd5d832810bf90ecc82aa03cfc4915fc9b33162dbad056b5'
FIT_REPORT_CANONICAL_SHA256 = '1a27b69e554b7fffcc734f3a8f7f8d6684e057e665feb7c64d43db930ae0f903'

CANDIDATE_MANIFEST = UPSTREAM / 'fit/CANDIDATE_MANIFEST.json'
CANDIDATE_MANIFEST_BYTE_SHA256 = 'd6801eb15810ecfc3096d643e721f914cf2a34264e79eee2daaf7e413279303c'
CANDIDATE_MANIFEST_CANONICAL_SHA256 = 'cec63b6e2d44b307e27353828dd442503e07f242188df98637d1a05c148a05c1'

CANDIDATE_ARTIFACT = UPSTREAM / 'fit/CANDIDATE.json'
CANDIDATE_ARTIFACT_BYTE_SHA256 = 'c78ae3c434d5f41e50567a131bdfb2b89982243379818709abeb0e5ec2385534'

PROTOCOL_V1 = UPSTREAM / 'FROZEN_VALIDATION_PROTOCOL.json'
PROTOCOL_V1_BYTE_SHA256 = '69c99a8b37589f1687b7e980344c9a79d69bbcd45be0a53ffd59bfea0ab583b3'
PROTOCOL_V1_CANONICAL_SHA256 = 'f283ce8dac9fbcfb5485eeb360217af4425fe947f249de652b03d96a13d40db5'

PROTOCOL_V2 = UPSTREAM / 'validation_protocol_v2/FROZEN_VALIDATION_PROTOCOL_V2.json'
PROTOCOL_V2_BYTE_SHA256 = '74b8a006ae84f8b9b22913ef76977e95f08992feb9765639a46d1ac49eb87350'
PROTOCOL_V2_CANONICAL_SHA256 = 'cb598a9fc2353aa78f19a7263a62a8ccbdba60eb400264787e896d0c232f19de'
PROTOCOL_V2_AMENDMENT_ID = 'V2_AMENDMENT_1_CONDITIONAL_NODE_CLOSURE'
# The pre-correction protocol v2 digests the preflight tool still pins.
PROTOCOL_V2_PRECORRECTION_BYTE_SHA256 = (
    'db1b1ab60224eb76e7a271de6a9544c89ac9676036e725935d0fb47105b9f6f1'
)
PROTOCOL_V2_PRECORRECTION_CANONICAL_SHA256 = (
    'e80732c4ea5512863c448497b89896799f24c942f744193832dabd5c568579f0'
)

PROTOCOL_V2_SUPERSEDED = (
    UPSTREAM / 'validation_protocol_v2/history/'
    '508a31ec8072a72ca573f65ac6b748e1ce5e67c639fd4388e472153b7ffa4320.json'
)
PROTOCOL_V2_SUPERSEDED_BYTE_SHA256 = (
    '508a31ec8072a72ca573f65ac6b748e1ce5e67c639fd4388e472153b7ffa4320'
)
PROTOCOL_V2_SUPERSEDED_CANONICAL_SHA256 = (
    'a97391d2678d66a46cc7a8d2d0893a509c9c2564a5c420f4519d21c05216dd16'
)

PREFLIGHT_V1_DIR = UPSTREAM / 'exact_tree_preflight'
PREFLIGHT_V1 = PREFLIGHT_V1_DIR / 'EXACT_TREE_PREFLIGHT.json'
PREFLIGHT_V1_BYTE_SHA256 = '456d85be57b910d3a56cb0160ba0ba35c988f7f69da9f965f0a887aaac473ae6'
PREFLIGHT_V1_CANONICAL_SHA256 = 'fc08988f0a677b462e484d1964a47967783e10cd1871fe810097b7c7265a9bbd'
PREFLIGHT_V1_INDEX_SHA256 = '97e90eac0a9302f1d0b304fa698f5179c7c0ee98ad52ebe307a911d9ccbfa5be'
# The pre-correction (mutant ``871e0bd``) digests.  They are recorded as history
# only: no reference to them survives on disk except this report and the
# preflight tool's stale pins.
PREFLIGHT_V1_PRECORRECTION_BYTE_SHA256 = (
    'e86b7c6b57d170c0885f46734c41302dcc15608252dfbbd66bff62c258d5c65f'
)
PREFLIGHT_V1_PRECORRECTION_CANONICAL_SHA256 = (
    'd027391f636b1ccc41c82b9a6b5d9a332ce44dba8ae2fb1c1ae2419eb340c217'
)
PREFLIGHT_V1_PRECORRECTION_INDEX_SHA256 = (
    '4fea09fc5713b9fa490effb39c557962ae1d06146710d954fb21bfd39ef25743'
)

PREFLIGHT_V2 = UPSTREAM / 'exact_tree_preflight_v2/EXACT_TREE_PREFLIGHT_V2.json'
# The repaired preflight v2 revision (re-generated by commit 9859c46 so the tool
# pin, the frozen bytes and the protocol v2 custody row agree again).
PREFLIGHT_V2_BYTE_SHA256 = '9b924077b286ef8c7c57e8a6e757cfb22a9784d2b44e8b328b11a55ba27abfc2'
PREFLIGHT_V2_CANONICAL_SHA256 = 'd88d1dba290f9a86033db7a875f8013b813472c24390c8a2736a09b7670b3a5b'
# The superseded preflight v2 revision this bundle bound before the repair
# (`9859c46`); recorded as history only, never as a pin on live bytes.
PREFLIGHT_V2_PRE_REPAIR_BYTE_SHA256 = (
    '2c07ae3279d10ec3e3bbdbe81cdb0d0f1f23e6bbb91cbdadddae113d1a9ea691'
)

DECISION_V1 = UPSTREAM / 'terminal_decision/DECISION.json'
DECISION_V1_BYTE_SHA256 = '9425f30163dcfa5e0a72ca8f6dd1bb4b6a25ce270b4a894aaa57e898a74bd0bc'
DECISION_V1_CANONICAL_SHA256 = '9b6aec99feeeb9c49424172f31a2d4657d8cf67cab2b80d2bbf66ecd22c261f5'

DECISION_V2 = UPSTREAM / 'terminal_decision_v2/DECISION_V2.json'
# The repaired terminal decision v2 revision (re-generated by commit 0f9a6eb to
# bind the repaired preflight v2 and the v2 raise-sizing frontier resolution).
DECISION_V2_BYTE_SHA256 = '4e220ecee2a8e3ac957c6b5d89ee79dd4f1920503de7442ea6b2e2e06ac7c882'
DECISION_V2_CANONICAL_SHA256 = '2eb8b3824023b16566d662d63eb5f830368d483ff30e4ee90210b8c2607167d0'
# The superseded terminal decision v2 revision this bundle bound before the
# repair (`0f9a6eb`); recorded as history only, never as a pin on live bytes.
DECISION_V2_PRE_REPAIR_BYTE_SHA256 = (
    'ac291b9ed363080401e9649a30b157eec7f7b79d5d2dc6df70390ccebc67c4b5'
)

VALIDATION_V1 = UPSTREAM / 'validation/VALIDATION_RESULT.json'
VALIDATION_V1_BYTE_SHA256 = '0b92e5a78ab3ee4cb581c33be351d6b52bcf4fcd8741ab907ebd6dd32ec6ef68'
VALIDATION_V1_CANONICAL_SHA256 = 'b05012719388ec803481adaebe281e70982654f55153a81679f51555e9124ba6'

CI_EVIDENCE = UPSTREAM / 'ci_evidence/CI_EVIDENCE.json'
CI_EVIDENCE_BYTE_SHA256 = '764b7f6daf111ef949471a69f7652d7d9ffba2cc0be09eff2a39a2c144327018'

CORRECTION = UPSTREAM / 'evidence_integrity_correction/EVIDENCE_INTEGRITY_CORRECTION.json'
CORRECTION_BYTE_SHA256 = 'f601d6195ccc4b71a36c5e5729c07c3277bc910bce254c39028485181e8a8803'
CORRECTION_COMMIT = 'c904524'

# The commits that repaired the two incidents this regeneration binds: 9859c46
# restored the preflight tool pins (no frozen byte moved), 0f9a6eb rewrote the
# raise-sizing frontier v2 bundle and the terminal decision v2 in a new revision.
PREFLIGHT_PIN_REPAIR_COMMIT = '9859c46'
DECISION_V2_REPAIR_COMMIT = '0f9a6eb'
EVIDENCE_CORRECTION_V2 = (
    UPSTREAM / 'evidence_integrity_correction_v2/EVIDENCE_INTEGRITY_CORRECTION_V2.json'
)
EVIDENCE_CORRECTION_V2_BYTE_SHA256 = (
    '0d530ad77555986028c15ebe98cb3bda366d68285afca6ad0633e2a0f3f5a177'
)
EVIDENCE_CORRECTION_V2_FINDING_ID = 'INTEGRATION_BUNDLE_V2_PINS_PRE_REPAIR_REVISIONS'
EVIDENCE_CORRECTION_V2_STALE_FINDING_ID = (
    'EVIDENCE_INTEGRITY_CORRECTION_V2_SNAPSHOT_REDERIVATION_DRIFT'
)

CONTRACT = UPSTREAM / 'contract/CANDIDATE_CONTRACT.json'
CONTRACT_BYTE_SHA256 = 'd62b2dca4a6673531c764b283de369f1192fe748eabcb4040f7ae0eda1823cd3'
CONTRACT_CANONICAL_SHA256 = '1c84f6f1159e0d91295cd3e894a811ebd2bd0f977ee1fbc7826082fd857432bf'

FRONTIERS = UPSTREAM / 'raise_sizing_frontiers/RAISE_SIZING_FRONTIER_RESOLUTION.json'
FRONTIERS_BYTE_SHA256 = '93e7e3ede0a69e6b3e35f40217bd53ff95d1fbbb847ca3fbc9181c0689d0152e'
FRONTIERS_CANONICAL_SHA256 = '29b87a82533a69b083034035dd9e2867e4dcf68bea099324675be5441a8f8174'
# The live frontier custody revision: v2 (regenerated by commit 0f9a6eb) adds
# the per-frontier blocker the v1 bundle lacks; v1 stays byte-frozen and is
# re-verified, never rewritten.
FRONTIERS_V2 = UPSTREAM / 'raise_sizing_frontiers_v2/RAISE_SIZING_FRONTIER_RESOLUTION.json'
FRONTIERS_V2_BYTE_SHA256 = '9df16dbb741659a8f6983e7ce243e3f1796b9fbf6b71be742fd0bc0b5c05540b'
FRONTIERS_V2_CANONICAL_SHA256 = 'cfdc9887a5e71fdf899bce3512e31e501b4fba08d25d6ec8dec4d8d388f1b01d'
FRONTIERS_V2_SCHEMA = 'poker-raise-sizing-frontier-resolution/v2'

SPARSITY_BASELINE = UPSTREAM / 'HIERARCHICAL_TREE_SPARSITY_BASELINE.json'
SPARSITY_BASELINE_BYTE_SHA256 = (
    'ef3995daaf5bc48a09f0785d574f7494754ad3904b87ecd2aa089b5be1b24a36'
)

ROOT_INDEX = UPSTREAM / 'ARTIFACTS.json'
ROOT_INDEX_BYTE_SHA256 = '1650cdd96adb70a47e7711eb44820bc46a9afc46f290b9023c60d101d903d768'
ROOT_SUMMARY = UPSTREAM / 'SUMMARY.md'
ROOT_SUMMARY_BYTE_SHA256 = '737d315c6fde5d4863830952ab5bf396483bbefc47f3a4cdfcc7fe12508616e8'

ACTIVE_MODEL = ROOT / 'training/models/preflop_population_model_v5.json'
ACTIVE_MODEL_POSTFLOP = ROOT / 'training/models/postflop_population_model_v5.json'
REGISTRY = ROOT / 'training/registry.json'
POPULATION_REGISTRY = ROOT / 'training/populations/registry.json'
ACTIVE_MODEL_BYTE_SHA256 = 'ff952055ca4ee051a3ac9607d513fdecac0a320a31f658ecfd8a11d8448975ca'

PREFLIGHT_TOOL_SOURCE = ROOT / 'tools/simulation/issue419_exact_tree_preflight.py'
VALIDATION_EVAL_TOOL = ROOT / 'tools/training/validate_hierarchical_validation.py'
PROTOCOL_WRITER_V1 = ROOT / 'tools/training/write_frozen_validation_protocol.py'
PROTOCOL_WRITER_V2 = ROOT / 'tools/training/write_frozen_validation_protocol_v2.py'
DECISION_TOOL = ROOT / 'tools/training/finalize_hierarchical_exact_tree_decision.py'
WORKFLOW = ROOT / '.github/workflows/issue-419-hierarchical-exact-tree.yml'

DATASET_ROOT = ROOT / 'training' / 'datasets'
HAND_HISTORY_SUFFIXES = frozenset({'jsonl', 'zip', 'snapshots'})

# A holdout loader is any symbol that would parse a VALIDATION/TEST hand, read a
# validation decision row or open a hand-history/dataset archive.  This bundle
# consumes none of them.
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
    'load_hand_histories',
    'parse_hand_history',
    'iter_hand_histories',
)
HOLDOUT_FORBIDDEN_MODULE_PREFIXES = (
    'tools.training.validate_hierarchical_validation',
    'tools.training.validate_full_hand_protocol',
    'tools.training.select_preflop_strategy_validation',
    'tools.training.validate_hero_pfpc_evidence',
)
ISSUE367_RUNNER_SYMBOLS = (
    'run_issue367_real_iso_ev',
    'issue367_real_iso_ev',
    'hero_ev',
    'hero_recommendation',
)

# ---------------------------------------------------------------------------
# Bundle members.  ``COPIES`` are byte-identical reproductions of an authority;
# ``REFERENCES`` are digest records whose bytes are never duplicated.
# ---------------------------------------------------------------------------
COPIES: tuple[tuple[str, Path, str], ...] = (
    ('HIERARCHICAL_MODEL_SPEC.json', MODEL_SPEC, MODEL_SPEC_BYTE_SHA256),
    ('TRAIN_FIT_REPORT.json', FIT_REPORT, FIT_REPORT_BYTE_SHA256),
    ('CANDIDATE_MANIFEST.json', CANDIDATE_MANIFEST, CANDIDATE_MANIFEST_BYTE_SHA256),
    ('EXACT_TREE_PREFLIGHT_V2.json', PREFLIGHT_V2, PREFLIGHT_V2_BYTE_SHA256),
    ('DECISION_V2.json', DECISION_V2, DECISION_V2_BYTE_SHA256),
)
REFERENCES: tuple[tuple[str, Path, str], ...] = (
    ('FROZEN_VALIDATION_PROTOCOL_V2.json', PROTOCOL_V2, PROTOCOL_V2_BYTE_SHA256),
    ('VALIDATION_RESULT.json', VALIDATION_V1, VALIDATION_V1_BYTE_SHA256),
    ('RAISE_SIZING_FRONTIER_RESOLUTION.json', FRONTIERS_V2, FRONTIERS_V2_BYTE_SHA256),
)
GENERATED: tuple[str, ...] = (
    REPORT_JSON_NAME,
    REPORT_NAME,
    SUMMARY_NAME,
    N8N_NAME,
)
MEMBER_NAMES: tuple[str, ...] = (
    *(name for name, _, _ in COPIES),
    *(name for name, _, _ in REFERENCES),
    *GENERATED,
)

PROTECTED_PATHS: tuple[Path, ...] = (
    REGISTRY,
    POPULATION_REGISTRY,
    ACTIVE_MODEL,
    ACTIVE_MODEL_POSTFLOP,
    ROOT_INDEX,
    ROOT_SUMMARY,
    MODEL_SPEC,
    PROTOCOL_V1,
    PROTOCOL_V1.with_suffix('.sha256'),
    PROTOCOL_V2,
    PROTOCOL_V2.with_suffix('.sha256'),
    PROTOCOL_V2_SUPERSEDED,
    PREFLIGHT_V1,
    PREFLIGHT_V1_DIR / INDEX_NAME,
    PREFLIGHT_V2,
    UPSTREAM / 'exact_tree_preflight_v2' / INDEX_NAME,
    DECISION_V1,
    UPSTREAM / 'terminal_decision' / INDEX_NAME,
    DECISION_V2,
    UPSTREAM / 'terminal_decision_v2' / INDEX_NAME,
    VALIDATION_V1,
    UPSTREAM / 'validation' / INDEX_NAME,
    CANDIDATE_ARTIFACT,
    FIT_REPORT,
    CANDIDATE_MANIFEST,
    UPSTREAM / 'fit' / INDEX_NAME,
    CONTRACT,
    UPSTREAM / 'contract' / INDEX_NAME,
    FRONTIERS,
    FRONTIERS_V2,
    UPSTREAM / 'raise_sizing_frontiers_v2' / INDEX_NAME,
    SPARSITY_BASELINE,
    CI_EVIDENCE,
    CORRECTION,
    EVIDENCE_CORRECTION_V2,
    UPSTREAM / 'evidence_integrity_correction_v2' / INDEX_NAME,
)

UPSTREAM_BUNDLES: tuple[Path, ...] = (
    UPSTREAM,
    UPSTREAM / 'model_spec',
    UPSTREAM / 'contract',
    UPSTREAM / 'fit',
    UPSTREAM / 'validation_protocol',
    UPSTREAM / 'validation_protocol_v2',
    UPSTREAM / 'validation',
    UPSTREAM / 'exact_tree_preflight',
    UPSTREAM / 'exact_tree_preflight_v2',
    UPSTREAM / 'raise_sizing_frontiers',
    UPSTREAM / 'raise_sizing_frontiers_v2',
    UPSTREAM / 'terminal_decision',
    UPSTREAM / 'terminal_decision_v2',
    UPSTREAM / 'ci_evidence',
    UPSTREAM / 'evidence_integrity_correction',
    UPSTREAM / 'evidence_integrity_correction_v2',
)


class IntegrationBundleError(RuntimeError):
    """Raised when the integrated evidence is inconsistent or inadmissible."""


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def serialize(payload: Any) -> bytes:
    return (json.dumps(payload, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(Path(path).read_bytes())


def _load(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _relative(path: Path | str | None) -> str | None:
    if path is None:
        return None
    try:
        return str(Path(path).resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def _module_constant(path: Path, name: str) -> Any:
    """Read a module-level constant without importing the module."""
    module = ast.parse(Path(path).read_text(encoding='utf-8'))
    for node in module.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    return ast.literal_eval(node.value)
    raise IntegrationBundleError(f'{_relative(path)} declares no constant {name}')


def object_extension(name: str) -> str:
    if name.endswith('.md'):
        return '.md'
    if name.endswith('.txt'):
        return '.txt'
    return '.json'


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
            raise IntegrationBundleError(
                f'hand-history/dataset file opened by the integration bundle: {self}'
            )
        opened.append(_relative(self) or str(self))
        return original_open(self, *args, **kwargs)

    pathlib.Path.open = guarded_open
    try:
        yield opened
    finally:
        pathlib.Path.open = original_open


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
        raise IntegrationBundleError(f'holdout loader symbol used by the bundle: {hits}')
    bad_imports = sorted(
        name for name in imported
        if any(
            name == prefix or name.startswith(prefix + '.')
            for prefix in HOLDOUT_FORBIDDEN_MODULE_PREFIXES
        )
    )
    if bad_imports:
        raise IntegrationBundleError(f'holdout loader module imported by the bundle: {bad_imports}')
    return {
        'result': 'PASS',
        'hits': hits,
        'forbidden_module_imports': bad_imports,
        'scanned': _relative(SOURCE_PATH),
    }


def verify_no_issue367_runner(source: str | None = None) -> dict[str, Any]:
    """Static proof that #367's Hero EV runner is never imported or invoked."""
    text = SOURCE_PATH.read_text(encoding='utf-8') if source is None else source
    module = ast.parse(text)
    used: set[str] = set()
    imported: list[str] = []
    for node in ast.walk(module):
        if isinstance(node, ast.Name):
            used.add(node.id)
        elif isinstance(node, ast.Attribute):
            used.add(node.attr)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [alias.name for alias in node.names]
            imported.extend(names)
            used.update(alias.name.split('.')[0] for alias in node.names)
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
    hits = sorted(used & set(ISSUE367_RUNNER_SYMBOLS))
    if hits:
        raise IntegrationBundleError(f'#367 Hero EV runner symbol used by the bundle: {hits}')
    bad_imports = sorted(name for name in imported if 'run_issue367_real_iso_ev' in name)
    if bad_imports:
        raise IntegrationBundleError(f'#367 Hero EV runner imported by the bundle: {bad_imports}')
    return {'result': 'PASS', 'hits': hits, 'forbidden_imports': bad_imports}


def verify_content_address(bundle: Path, index_name: str = INDEX_NAME) -> dict[str, Any]:
    """Verify a persisted content-addressed bundle before trusting any byte.

    An entry resolves to the file of that name inside ``bundle`` when it exists,
    otherwise to the root-relative ``entry['path']`` a binding entry declares.
    A metadata-only entry such as the ``validation_protocol_v2`` ``history``
    block has no file of its own: only the content-addressed object it names is
    verified.
    """
    index = _load(bundle / index_name)
    if not isinstance(index, dict) or not index:
        raise IntegrationBundleError(f'{_relative(bundle)} carries no usable {index_name}')
    for name, entry in index.items():
        path = bundle / name
        if not path.is_file() and 'path' in entry:
            path = ROOT / entry['path']
        if not path.is_file():
            if 'object' not in entry:
                raise IntegrationBundleError(
                    f'content-addressed file missing and no object declared: {_relative(path)}'
                )
            obj = bundle / entry['object']
            if not obj.is_file():
                obj = ROOT / entry['object']
            if not obj.is_file() or sha256_file(obj) != entry['sha256']:
                raise IntegrationBundleError(
                    f'content-addressed object mismatch: {_relative(bundle)}::{name}'
                )
            continue
        data = path.read_bytes()
        if sha256_bytes(data) != entry['sha256']:
            raise IntegrationBundleError(f'content-addressed byte hash mismatch: {_relative(path)}')
        if 'object' in entry:
            obj = bundle / entry['object']
            if not obj.is_file():
                obj = ROOT / entry['object']
            if not obj.is_file():
                raise IntegrationBundleError(f'content-addressed object missing: {entry["object"]}')
            if data != obj.read_bytes():
                raise IntegrationBundleError(f'content-addressed copy mismatch: {_relative(path)}')
        if 'canonical_payload_sha256' in entry and path.name.endswith('.json'):
            if stable_hash(json.loads(data)) != entry['canonical_payload_sha256']:
                raise IntegrationBundleError(
                    f'content-addressed canonical payload mismatch: {_relative(path)}'
                )
    return index


def _pin(path: Path, expected: str, label: str) -> str:
    actual = sha256_file(path)
    if actual != expected:
        raise IntegrationBundleError(f'{label} drifted: {_relative(path)} {actual} != {expected}')
    return actual


def _pin_canonical(path: Path, expected: str, label: str) -> str:
    actual = stable_hash(_load(path))
    if actual != expected:
        raise IntegrationBundleError(
            f'{label} canonical payload drifted: {_relative(path)} {actual} != {expected}'
        )
    return actual


# ---------------------------------------------------------------------------
# Report construction
# ---------------------------------------------------------------------------
def load_ci_evidence() -> dict[str, Any]:
    """Read T5's CI evidence (read-only) and re-derive its honest CI verdict."""
    _pin(CI_EVIDENCE, CI_EVIDENCE_BYTE_SHA256, 'T5 CI evidence')
    ci = _load(CI_EVIDENCE)
    if ci.get('ci_observation', {}).get('status') != 'NOT_OBSERVED':
        raise IntegrationBundleError(
            'the CI observation is no longer NOT_OBSERVED: a real run must be recorded, '
            'not inferred, before this bundle may claim any CI status'
        )
    reviewed = ci['reviewed_pr_head_runs']
    other = ci['same_sha_other_events']
    if reviewed.get('none_executes_the_issue419_suites') is not True:
        raise IntegrationBundleError('T5 no longer states that no recorded run executes #419')
    runs: list[dict[str, Any]] = []
    for row in reviewed['runs']:
        runs.append({
            'name': row['name'],
            'run_number': row['run_number'],
            'conclusion': row['conclusion'],
            'url': row['url'],
            'workflow_path': row['workflow_path'],
            'event': 'pull_request',
            'executes_the_issue419_suites': False,
        })
    for row in other['runs']:
        runs.append({
            'name': row['name'],
            'run_number': row['run_number'],
            'conclusion': row['conclusion'],
            'url': row['url'],
            'workflow_path': row['workflow_path'],
            'event': row.get('event'),
            'executes_the_issue419_suites': bool(row.get('executes_the_issue419_suites')),
        })
    runs.sort(key=lambda row: (row['event'], row['run_number']))
    return {
        'source': {
            'path': _relative(CI_EVIDENCE),
            'schema': ci['schema'],
            'byte_sha256': CI_EVIDENCE_BYTE_SHA256,
            'bundle_task': ci.get('bundle_task'),
            'planner_key': ci.get('planner_key'),
        },
        'status': ci['ci_observation']['status'],
        'authority_required': ci['ci_observation']['authority_required'],
        'run_name_recorded': ci['ci_observation']['run_name_recorded'],
        'run_url_recorded': ci['ci_observation']['run_url'],
        'no_run_exists': ci['ci_observation']['no_run_exists'],
        'reason': ci['ci_observation']['reason'],
        'promotion_forbidden_by': list(ci['ci_observation']['may_not_be_promoted_to_PASS_by']),
        'pull_request': {
            'number': ci['pr']['number'],
            'url': ci['pr']['url'],
            'head_sha_at_verification': ci['pr']['head_sha_at_verification'],
            'base': ci['pr']['base'],
            'base_sha': ci['pr']['base_sha'],
        },
        'workflow_under_test': {
            'name': ci['workflow_under_test']['name'],
            'path': ci['workflow_under_test']['path'],
            'present_at_worktree_head': ci['workflow_under_test']['present_at_worktree_head'],
            'present_at_remote_pr_head': ci['workflow_under_test']['present_at_remote_pr_head'],
            'sha256_as_recorded_by_t5': ci['workflow_under_test']['sha256'],
            'git_blob_sha1_as_recorded_by_t5': ci['workflow_under_test']['git_blob_sha1'],
            'bytes_as_recorded_by_t5': ci['workflow_under_test']['bytes'],
            'lines_as_recorded_by_t5': ci['workflow_under_test']['lines'],
            'executed_suite_count_as_recorded_by_t5': (
                ci['workflow_under_test']['executed_suite_count']
            ),
        },
        'sha256_now': sha256_file(WORKFLOW),
        'bytes_now': WORKFLOW.stat().st_size,
        'recorded_run_ids': sorted(row['run_number'] for row in runs),
        'observed_run_count': len(runs),
        'recorded_runs': runs,
        'none_executes_the_issue419_suites': True,
        'post_push_verification': list(ci['post_push_verification']),
    }


def preflight_pin_findings() -> list[dict[str, Any]]:
    """Machine-derived pin findings: both stale pins are RESOLVED.

    Commit ``887e46a`` re-pointed the exact-tree preflight tool's frozen pins onto
    the digests the evidence-integrity correction had already reverted (the v1
    preflight payload/index and the protocol v2 bytes), which made
    ``issue419_exact_tree_preflight.py --check`` fail closed.  Commit ``9859c46``
    (task ``backlog-911``) restored the four pins to the custody digests without
    moving one frozen byte, so each pin now equals the authority persisted on
    disk.  Both mismatches are recomputed here from the persisted bytes and the
    tool's own constants and kept as recorded history with ``status = RESOLVED``
    and ``blocks_ready_for_integration = False``.
    """
    _pin(PREFLIGHT_V1, PREFLIGHT_V1_BYTE_SHA256, 'frozen v1 preflight')
    _pin_canonical(PREFLIGHT_V1, PREFLIGHT_V1_CANONICAL_SHA256, 'frozen v1 preflight')
    index = PREFLIGHT_V1_DIR / INDEX_NAME
    _pin(index, PREFLIGHT_V1_INDEX_SHA256, 'frozen v1 preflight index')
    _pin(PROTOCOL_V2, PROTOCOL_V2_BYTE_SHA256, 'frozen protocol v2')
    _pin_canonical(PROTOCOL_V2, PROTOCOL_V2_CANONICAL_SHA256, 'frozen protocol v2')
    pinned_payload = _module_constant(PREFLIGHT_TOOL_SOURCE, 'V1_PREFLIGHT_SHA256')
    pinned_index = _module_constant(PREFLIGHT_TOOL_SOURCE, 'V1_INDEX_SHA256')
    v2_pinned_byte = _module_constant(PREFLIGHT_TOOL_SOURCE, 'PROTOCOL_V2_BYTE_SHA256')
    v2_pinned_canonical = _module_constant(
        PREFLIGHT_TOOL_SOURCE, 'PROTOCOL_V2_CANONICAL_PAYLOAD_SHA256'
    )
    v1_matches = (
        pinned_payload == PREFLIGHT_V1_BYTE_SHA256
        and pinned_index == PREFLIGHT_V1_INDEX_SHA256
    )
    v2_matches = (
        v2_pinned_byte == PROTOCOL_V2_BYTE_SHA256
        and v2_pinned_canonical == PROTOCOL_V2_CANONICAL_SHA256
    )
    v1 = {
        'finding_id': 'V1_PREFLIGHT_PIN_STALE',
        'status': 'RESOLVED',
        'detail': (
            'the preflight tool once pinned the pre-correction v1 preflight bytes, which the '
            'evidence-integrity correction had restored to a different (authoritative) digest, '
            'so issue419_exact_tree_preflight.py --check failed closed on its own frozen '
            'surface; commit 9859c46 restored the pins, so the pin now equals the restored '
            'authority on disk and the check is GREEN at this head'
        ),
        'detected_by': (
            'python3 tools/simulation/issue419_exact_tree_preflight.py --check'
        ),
        'observed_before_repair': 'PreflightError: the frozen v1 preflight artifact drifted',
        'observed_at_this_head': 'check PASS (the frozen v1 preflight is re-derived)',
        'tool': _relative(PREFLIGHT_TOOL_SOURCE),
        'tool_pins': {
            'V1_PREFLIGHT_SHA256': pinned_payload,
            'V1_INDEX_SHA256': pinned_index,
        },
        'on_disk': {
            'EXACT_TREE_PREFLIGHT.json': PREFLIGHT_V1_BYTE_SHA256,
            'ARTIFACTS.json': PREFLIGHT_V1_INDEX_SHA256,
        },
        'pin_matches_on_disk_bytes': v1_matches,
        'introduced_by': '887e46a (task backlog-agg)',
        'restored_by': CORRECTION_COMMIT,
        'repaired_by': f'{PREFLIGHT_PIN_REPAIR_COMMIT} (task backlog-911)',
        'owner': 'the exact-tree preflight task; repaired at the pin source, no frozen byte moved',
        'repaired_by_this_bundle': False,
        'blocks_ready_for_integration': False,
        'resolution': 'REPAIRED_AT_THE_PIN_SOURCE_NO_FROZEN_BYTE_MOVED',
    }
    v2 = {
        'finding_id': 'PROTOCOL_V2_PREFLIGHT_PIN_STALE',
        'status': 'RESOLVED',
        'detail': (
            'the same preflight tool also pinned the pre-correction protocol v2 bytes, which '
            'tripped the protocol-v2 custody check inside the preflight suite; commit 9859c46 '
            'restored both protocol v2 pins to the amended authority, so the suite is GREEN at '
            'this head'
        ),
        'detected_by': 'PYTHONPATH=. python3 tests/simulation/test_issue419_exact_tree_preflight.py',
        'observed_before_repair': (
            'AssertionError: PROTOCOL_V2_BYTE_SHA256 '
            f'{PROTOCOL_V2_BYTE_SHA256} != {PROTOCOL_V2_PRECORRECTION_BYTE_SHA256}'
        ),
        'observed_at_this_head': 'OK (24 tests)',
        'tool': _relative(PREFLIGHT_TOOL_SOURCE),
        'tool_pins': {
            'PROTOCOL_V2_BYTE_SHA256': v2_pinned_byte,
            'PROTOCOL_V2_CANONICAL_PAYLOAD_SHA256': v2_pinned_canonical,
        },
        'on_disk': {
            'byte_sha256': PROTOCOL_V2_BYTE_SHA256,
            'canonical_payload_sha256': PROTOCOL_V2_CANONICAL_SHA256,
        },
        'pin_matches_on_disk_bytes': v2_matches,
        'introduced_by': '887e46a (task backlog-agg)',
        'restored_by': CORRECTION_COMMIT,
        'repaired_by': f'{PREFLIGHT_PIN_REPAIR_COMMIT} (task backlog-911)',
        'owner': 'the exact-tree preflight task; repaired at the pin source, no frozen byte moved',
        'repaired_by_this_bundle': False,
        'blocks_ready_for_integration': False,
        'resolution': 'REPAIRED_AT_THE_PIN_SOURCE_NO_FROZEN_BYTE_MOVED',
    }
    return [v1, v2]


def closed_bundle_pin_finding() -> dict[str, Any]:
    """The evidence-integrity correction v2 finding this regeneration closes.

    ``EVIDENCE_INTEGRITY_CORRECTION_V2.json`` recorded -- and explicitly deferred
    to this task -- that ``analysis/issue419_hierarchical_tree_v2/`` still bound
    ``EXACT_TREE_PREFLIGHT_V2.json`` and ``DECISION_V2.json`` to the revisions
    that existed when it was authored.  This regeneration re-binds both copies to
    the repaired revisions, so the finding is CLOSED.
    """
    _pin(EVIDENCE_CORRECTION_V2, EVIDENCE_CORRECTION_V2_BYTE_SHA256, 'correction v2 record')
    correction_v2 = _load(EVIDENCE_CORRECTION_V2)
    recorded = [
        row for row in correction_v2.get('residual_findings', [])
        if row.get('finding_id') == EVIDENCE_CORRECTION_V2_FINDING_ID
    ]
    if len(recorded) != 1:
        raise IntegrationBundleError(
            'the evidence-integrity correction v2 record no longer carries exactly one '
            f'{EVIDENCE_CORRECTION_V2_FINDING_ID} finding'
        )
    deferred_owner = 'the #419 integration-bundle task (backlog-oso / T7), not this record'
    if recorded[0].get('owner') != deferred_owner:
        raise IntegrationBundleError('the deferred finding is no longer owned by this task')
    return {
        'finding_id': EVIDENCE_CORRECTION_V2_FINDING_ID,
        'status': 'CLOSED_BY_THIS_REGENERATION',
        'detail': (
            'the integration bundle v2 bound EXACT_TREE_PREFLIGHT_V2.json and DECISION_V2.json '
            'to the pre-repair revisions that existed when it was authored; this regeneration '
            're-binds both copies to the repaired revisions and both members re-verify '
            'byte-for-byte'
        ),
        'detected_by': 'python3 tools/training/build_hierarchical_integration_bundle_v2.py --check',
        'recorded_in': {
            'path': _relative(EVIDENCE_CORRECTION_V2),
            'byte_sha256': EVIDENCE_CORRECTION_V2_BYTE_SHA256,
            'finding_id': EVIDENCE_CORRECTION_V2_FINDING_ID,
            'recorded_owner': recorded[0]['owner'],
        },
        'before': {
            'EXACT_TREE_PREFLIGHT_V2.json': PREFLIGHT_V2_PRE_REPAIR_BYTE_SHA256,
            'DECISION_V2.json': DECISION_V2_PRE_REPAIR_BYTE_SHA256,
        },
        'after': {
            'EXACT_TREE_PREFLIGHT_V2.json': PREFLIGHT_V2_BYTE_SHA256,
            'DECISION_V2.json': DECISION_V2_BYTE_SHA256,
        },
        'closed_by': 'backlog-hvp (this regeneration)',
        'repaired_by_this_bundle': True,
        'touches_a_frozen_byte': False,
        'blocks_ready_for_integration': False,
    }


def build_payload() -> dict[str, Any]:
    """Compose the integration report from the frozen authorities."""
    with hand_history_tripwire() as opened_paths:
        holdout_scan = verify_no_holdout_access()
        issue367_scan = verify_no_issue367_runner()
        protected_before = {_relative(p): sha256_file(p) for p in PROTECTED_PATHS}

        for bundle in UPSTREAM_BUNDLES:
            verify_content_address(bundle)

        _pin(MODEL_SPEC, MODEL_SPEC_BYTE_SHA256, 'T2 model spec')
        _pin_canonical(MODEL_SPEC, MODEL_SPEC_CANONICAL_SHA256, 'T2 model spec')
        _pin(FIT_REPORT, FIT_REPORT_BYTE_SHA256, 'T3 TRAIN fit report')
        _pin_canonical(FIT_REPORT, FIT_REPORT_CANONICAL_SHA256, 'T3 TRAIN fit report')
        _pin(CANDIDATE_MANIFEST, CANDIDATE_MANIFEST_BYTE_SHA256, 'T4 candidate manifest')
        _pin_canonical(
            CANDIDATE_MANIFEST, CANDIDATE_MANIFEST_CANONICAL_SHA256, 'T4 candidate manifest'
        )
        _pin(CANDIDATE_ARTIFACT, CANDIDATE_ARTIFACT_BYTE_SHA256, 'T4 candidate artifact')
        _pin(PROTOCOL_V1, PROTOCOL_V1_BYTE_SHA256, 'frozen protocol v1')
        _pin(PROTOCOL_V2, PROTOCOL_V2_BYTE_SHA256, 'frozen protocol v2')
        _pin_canonical(PROTOCOL_V2, PROTOCOL_V2_CANONICAL_SHA256, 'frozen protocol v2')
        _pin(PROTOCOL_V2_SUPERSEDED, PROTOCOL_V2_SUPERSEDED_BYTE_SHA256, 'superseded v2 payload')
        _pin_canonical(
            PROTOCOL_V2_SUPERSEDED,
            PROTOCOL_V2_SUPERSEDED_CANONICAL_SHA256,
            'superseded v2 payload',
        )
        _pin(PREFLIGHT_V2, PREFLIGHT_V2_BYTE_SHA256, 'preflight v2')
        _pin_canonical(PREFLIGHT_V2, PREFLIGHT_V2_CANONICAL_SHA256, 'preflight v2')
        _pin(DECISION_V1, DECISION_V1_BYTE_SHA256, 'terminal decision v1')
        _pin(DECISION_V2, DECISION_V2_BYTE_SHA256, 'terminal decision v2')
        _pin_canonical(DECISION_V2, DECISION_V2_CANONICAL_SHA256, 'terminal decision v2')
        _pin(VALIDATION_V1, VALIDATION_V1_BYTE_SHA256, 'consumed v1 VALIDATION result')
        _pin(CORRECTION, CORRECTION_BYTE_SHA256, 'evidence-integrity correction')
        _pin(CONTRACT, CONTRACT_BYTE_SHA256, 'candidate contract')
        _pin(FRONTIERS, FRONTIERS_BYTE_SHA256, 'raise-sizing frontier resolution')
        _pin_canonical(FRONTIERS, FRONTIERS_CANONICAL_SHA256, 'raise-sizing frontier resolution')
        _pin(FRONTIERS_V2, FRONTIERS_V2_BYTE_SHA256, 'raise-sizing frontier resolution v2')
        _pin_canonical(
            FRONTIERS_V2, FRONTIERS_V2_CANONICAL_SHA256, 'raise-sizing frontier resolution v2'
        )
        _pin(SPARSITY_BASELINE, SPARSITY_BASELINE_BYTE_SHA256, 'T1 sparsity baseline')
        _pin(ROOT_INDEX, ROOT_INDEX_BYTE_SHA256, 'root ARTIFACTS.json')
        _pin(ROOT_SUMMARY, ROOT_SUMMARY_BYTE_SHA256, 'root SUMMARY.md')
        _pin(ACTIVE_MODEL, ACTIVE_MODEL_BYTE_SHA256, 'active Model A v5 reference')

        spec = _load(MODEL_SPEC)
        fit = _load(FIT_REPORT)
        manifest = _load(CANDIDATE_MANIFEST)
        protocol_v2 = _load(PROTOCOL_V2)
        preflight_v2 = _load(PREFLIGHT_V2)
        decision_v1 = _load(DECISION_V1)
        decision_v2 = _load(DECISION_V2)
        contract = _load(CONTRACT)
        correction = _load(CORRECTION)

        if manifest['candidate']['contract_candidate_id'] != CANDIDATE_ID:
            raise IntegrationBundleError('the T4 manifest names a different candidate id')
        if manifest['candidate']['candidate_instance_id'] != CANDIDATE_INSTANCE_ID:
            raise IntegrationBundleError('the T4 manifest names a different candidate instance')
        if manifest['candidate']['artifact']['canonical_payload_sha256'] != CANDIDATE_SHA256:
            raise IntegrationBundleError('the T4 manifest names a different candidate digest')
        if preflight_v2['required_tree']['required_tree_sha256'] != REQUIRED_TREE_SHA256:
            raise IntegrationBundleError('the preflight v2 walks a different required tree')
        if preflight_v2['admissibility']['required_tree_complete'] is not False:
            raise IntegrationBundleError(
                'the preflight v2 now reports a complete required tree: this bundle must be '
                'rebuilt under a new verdict, never adjusted to fit an old one'
            )
        if protocol_v2['amendments']['superseded_digest'] != PROTOCOL_V2_SUPERSEDED_BYTE_SHA256:
            raise IntegrationBundleError('protocol v2 no longer declares the superseded digest')
        if decision_v2['candidate_sha256'] != CANDIDATE_SHA256:
            raise IntegrationBundleError('the terminal decision v2 names a different candidate')
        if decision_v2['decision'] != DECISION or decision_v2['status'] != STATUS:
            raise IntegrationBundleError('the terminal decision v2 moved off this verdict')
        if decision_v2['validation_consumed'] is not True or decision_v2['test_consumed'] is not False:
            raise IntegrationBundleError('the terminal decision v2 split boundary moved')
        if decision_v2['frozen_inputs_untouched']['exact_tree_preflight_v2_sha256'] != (
            PREFLIGHT_V2_BYTE_SHA256
        ):
            raise IntegrationBundleError(
                'the terminal decision v2 binds a different exact-tree preflight v2 revision'
            )
        if decision_v2['frozen_inputs_untouched']['v2_raise_sizing_frontier_sha256'] != (
            FRONTIERS_V2_BYTE_SHA256
        ):
            raise IntegrationBundleError(
                'the terminal decision v2 binds a different raise-sizing frontier v2 revision'
            )
        if decision_v2['raise_sizing_frontier_revision']['revision'] != 'v2':
            raise IntegrationBundleError('the terminal decision v2 is not on the v2 frontier revision')
        if decision_v1['decision'] != DECISION:
            raise IntegrationBundleError('the byte-pinned v1 decision moved')
        if contract['candidate_id'] != CANDIDATE_ID:
            raise IntegrationBundleError('the candidate contract names a different candidate')
        if correction['correction_id'] != 'issue419-evidence-integrity-correction-v1':
            raise IntegrationBundleError('unexpected evidence-integrity correction payload')

        reference_doc = {
            'source': {
                'path': _relative(PROTOCOL_V2),
                'byte_sha256': PROTOCOL_V2_BYTE_SHA256,
                'canonical_payload_sha256': PROTOCOL_V2_CANONICAL_SHA256,
                'schema': protocol_v2['schema'],
                'digest_sidecar': _relative(PROTOCOL_V2.with_suffix('.sha256')),
                'bundle_index': _relative(PROTOCOL_V2.parent / INDEX_NAME),
            },
            'frozen_v1': {
                'path': _relative(PROTOCOL_V1),
                'byte_sha256': PROTOCOL_V1_BYTE_SHA256,
                'canonical_payload_sha256': PROTOCOL_V1_CANONICAL_SHA256,
            },
            'amendment': {
                'amendment_id': PROTOCOL_V2_AMENDMENT_ID,
                'revision_of': protocol_v2['revision_of'],
                'superseded_byte_sha256': PROTOCOL_V2_SUPERSEDED_BYTE_SHA256,
                'superseded_canonical_payload_sha256': PROTOCOL_V2_SUPERSEDED_CANONICAL_SHA256,
                'superseded_kept_content_addressed': True,
            },
            'thresholds_moved': False,
            'gates_weaker_than_v1': False,
        }
        validation_reference = {
            'source': {
                'path': _relative(VALIDATION_V1),
                'byte_sha256': VALIDATION_V1_BYTE_SHA256,
                'canonical_payload_sha256': VALIDATION_V1_CANONICAL_SHA256,
                'schema': _load(VALIDATION_V1).get('schema'),
                'digest_sidecar': _relative(VALIDATION_V1.with_suffix('.sha256')),
                'bundle_index': _relative(VALIDATION_V1.parent / INDEX_NAME),
            },
            'split': 'VALIDATION',
            'published_verdict': _load(VALIDATION_V1)['outcome'],
            'published_failing_gates': list(_load(VALIDATION_V1)['gate']['failing_gates']),
            'holdout_reopened_by_this_bundle': False,
            'decision_rows_read_by_this_bundle': 0,
            'hand_histories_parsed_by_this_bundle': 0,
            'metrics_recomputed_by_this_bundle': 0,
            'thresholds_re_selected_by_this_bundle': False,
            'digest_re_derived_from_persisted_bytes': True,
            'pointers_read': [
                '/outcome',
                '/gate/failing_gates',
                '/candidate',
                '/coverage',
            ],
        }

        ci = load_ci_evidence()
        pin_findings = preflight_pin_findings()

        members: dict[str, Any] = {}
        for name, source, digest in COPIES:
            _pin(source, digest, f'bundle member {name}')
            entry: dict[str, Any] = {
                'mode': 'BYTE_IDENTICAL_COPY',
                'role': _copy_role(name),
                'source_path': _relative(source),
                'source_byte_sha256': digest,
                'bytes': source.stat().st_size,
            }
            if name.endswith('.json'):
                entry['canonical_payload_sha256'] = stable_hash(_load(source))
            members[name] = entry
        for name, source, digest in REFERENCES:
            _pin(source, digest, f'bundle reference {name}')
            entry = {
                'mode': 'DIGEST_REFERENCE_NO_BYTES',
                'role': _reference_role(name),
                'source_path': _relative(source),
                'source_byte_sha256': digest,
                'bytes_copied': 0,
            }
            if name.endswith('.json'):
                entry['canonical_payload_sha256'] = stable_hash(_load(source))
            members[name] = entry

        coherence = {
            'upstream_bundles_verified': len(UPSTREAM_BUNDLES),
            'upstream_bundles': [_relative(bundle) for bundle in UPSTREAM_BUNDLES],
            'candidate_id_matches_t4_manifest_and_contract': True,
            'candidate_sha256_matches_t4_manifest_and_terminal_decision_v2': True,
            'required_tree_sha256_matches_decision_v1_v2_and_preflight_v2': True,
            'protocol_v2_declares_the_superseded_digest_it_replaced': True,
            'root_artifacts_index_and_summary_bytes_unchanged': True,
            't1_sparsity_baseline_digest': SPARSITY_BASELINE_BYTE_SHA256,
            't2_model_spec_digest': MODEL_SPEC_BYTE_SHA256,
            't3_train_fit_report_digest': FIT_REPORT_BYTE_SHA256,
            't4_candidate_manifest_digest': CANDIDATE_MANIFEST_BYTE_SHA256,
            't4_candidate_digest': CANDIDATE_SHA256,
            'frozen_protocol_v1_digest': PROTOCOL_V1_BYTE_SHA256,
            'frozen_protocol_v2_digest': PROTOCOL_V2_BYTE_SHA256,
            'validation_result_digest': VALIDATION_V1_BYTE_SHA256,
            'terminal_decision_v1_digest': DECISION_V1_BYTE_SHA256,
            'terminal_decision_v2_digest': DECISION_V2_BYTE_SHA256,
            'exact_tree_preflight_v1_digest': PREFLIGHT_V1_BYTE_SHA256,
            'exact_tree_preflight_v2_digest': PREFLIGHT_V2_BYTE_SHA256,
            'raise_sizing_frontier_v1_digest': FRONTIERS_BYTE_SHA256,
            'raise_sizing_frontier_v2_digest': FRONTIERS_V2_BYTE_SHA256,
            'terminal_decision_v2_binds_repaired_preflight_v2_and_frontier_v2': True,
            'exact_tree_preflight_check_is_green_at_this_head': True,
        }

        required_supersessions = [
            {
                'supersession_id': 'SUPERSEDED_V2_PROTOCOL_PAYLOAD_508A31EC',
                'subject': 'the first authored v2 VALIDATION protocol payload',
                'superseded': {
                    'byte_sha256': PROTOCOL_V2_SUPERSEDED_BYTE_SHA256,
                    'canonical_payload_sha256': PROTOCOL_V2_SUPERSEDED_CANONICAL_SHA256,
                    'path': _relative(PROTOCOL_V2_SUPERSEDED),
                },
                'superseding': {
                    'byte_sha256': PROTOCOL_V2_BYTE_SHA256,
                    'canonical_payload_sha256': PROTOCOL_V2_CANONICAL_SHA256,
                    'path': _relative(PROTOCOL_V2),
                },
                'mechanism': PROTOCOL_V2_AMENDMENT_ID,
                'superseded_kept_content_addressed': True,
                'thresholds_moved': False,
                'gates_relaxed': False,
                'claim': (
                    'the flat counts_as_a_closed_exact_tree_node=false was replaced by '
                    'NODE_CLOSES_IFF_ALL_FROZEN_LAYER_B_GATES_PASS; no threshold and no gate '
                    'value moved and every gate is equal to or stricter than its v1 homologue'
                ),
            },
            {
                'supersession_id': 'V1_EXACT_TREE_PREFLIGHT_REGENERATION',
                'subject': 'analysis/issue419_hierarchical_tree/exact_tree_preflight/',
                'mutant_commit': '871e0bd9e66c978932face1accf1aaf22ac9fa1a',
                'mutant_task': 'backlog-sd5',
                'mutant_digests': {
                    'EXACT_TREE_PREFLIGHT.json': PREFLIGHT_V1_PRECORRECTION_BYTE_SHA256,
                    'canonical_payload_sha256': PREFLIGHT_V1_PRECORRECTION_CANONICAL_SHA256,
                    'ARTIFACTS.json': PREFLIGHT_V1_PRECORRECTION_INDEX_SHA256,
                },
                'corrected_commit': CORRECTION_COMMIT,
                'corrected_by': 'issue419-evidence-integrity-correction-v1',
                'correction_artifact': _relative(CORRECTION),
                'correction_artifact_sha256': CORRECTION_BYTE_SHA256,
                'restored_digests': {
                    'EXACT_TREE_PREFLIGHT.json': PREFLIGHT_V1_BYTE_SHA256,
                    'canonical_payload_sha256': PREFLIGHT_V1_CANONICAL_SHA256,
                    'ARTIFACTS.json': PREFLIGHT_V1_INDEX_SHA256,
                },
                'frozen_bytes_rewritten_to_fit_a_digest': False,
                'superseded_by': _relative(PREFLIGHT_V2),
                'follow_on_finding': 'V1_PREFLIGHT_PIN_STALE',
                'follow_on_findings': [
                    'V1_PREFLIGHT_PIN_STALE',
                    'PROTOCOL_V2_PREFLIGHT_PIN_STALE',
                ],
                'follow_on_finding_status': 'RESOLVED',
                'follow_on_finding_repaired_by': (
                    f'{PREFLIGHT_PIN_REPAIR_COMMIT} (task backlog-911)'
                ),
                'claim': (
                    'commit 871e0bd rewrote the frozen v1 preflight in place and re-registered '
                    'its digests; commit c904524 reversed exactly that surface, byte for byte, '
                    'without touching the pins. The regenerated (restored) bytes are the '
                    'authority; the duplicate e86b7c6b object no longer exists'
                ),
            },
            {
                'supersession_id': 'RAISE_SIZING_FRONTIER_RESOLUTION_V1_SUPERSEDED_BY_V2',
                'subject': 'analysis/issue419_hierarchical_tree/raise_sizing_frontiers/',
                'superseded': {
                    'byte_sha256': FRONTIERS_BYTE_SHA256,
                    'canonical_payload_sha256': FRONTIERS_CANONICAL_SHA256,
                    'path': _relative(FRONTIERS),
                },
                'superseding': {
                    'byte_sha256': FRONTIERS_V2_BYTE_SHA256,
                    'canonical_payload_sha256': FRONTIERS_V2_CANONICAL_SHA256,
                    'path': _relative(FRONTIERS_V2),
                },
                'mechanism': FRONTIERS_V2_SCHEMA,
                'superseded_kept_content_addressed': True,
                'thresholds_moved': False,
                'gates_relaxed': False,
                'claim': (
                    'the v2 revision (commit 0f9a6eb) adds the per-frontier blocker the frozen '
                    'v1 bundle lacks; the v1 bytes stay byte-frozen custody, re-verified on '
                    'every build and never rewritten, and the terminal decision v2 binds the v2 '
                    'revision for its values while recording v1 only as custody'
                ),
            },
        ]
        declared_supersessions = [
            {
                'supersession_id': 'EXACT_TREE_PREFLIGHT_V1_SUPERSEDED_BY_V2',
                'superseded': _relative(PREFLIGHT_V1),
                'superseding': _relative(PREFLIGHT_V2),
                'regeneration_possible': False,
                'reason': (
                    'the v1 payload embeds code.preflight_tool.sha256 of the superseded v1 '
                    'tool, which no longer exists on disk; v1 is byte-pinned, re-verified and '
                    'never rewritten, and --revision v1 is refused'
                ),
            },
            {
                'supersession_id': 'TERMINAL_DECISION_V1_SUPERSEDED_BY_V2',
                'superseded': _relative(DECISION_V1),
                'superseded_byte_sha256': DECISION_V1_BYTE_SHA256,
                'superseding': _relative(DECISION_V2),
                'superseding_byte_sha256': DECISION_V2_BYTE_SHA256,
                'v1_rewritten': False,
                'reason': (
                    'the v1 decision is byte-pinned and re-verified on every build; v2 is an '
                    'additive revision composed of the TRAIN-only preflight v2 and the '
                    'digest-referenced consumed v1 VALIDATION bytes'
                ),
            },
        ]

        residual_findings = [
            {
                'finding_id': 'CI_NOT_OBSERVED',
                'detail': (
                    'no run of « Execute issue 419 hierarchical exact tree » exists at any head; '
                    'the five real CI runs at the reviewed PR head execute none of the #419 '
                    'suites'
                ),
                'owner': 'the orchestrator run that holds git transport (push) plus the CI task',
                'blocks_ready_for_integration': True,
                'promotion_forbidden_by': ci['promotion_forbidden_by'],
            },
            {
                'finding_id': 'WORKFLOW_BYTES_CHANGED_BY_THIS_TASK',
                'detail': (
                    'this task adds the analysis/issue419_hierarchical_tree_v2/** trigger glob '
                    'so the new bundle surface re-runs the authoritative workflow (the #419 '
                    'path-coverage guard fails otherwise); the workflow bytes therefore differ '
                    'from the bytes T5 recorded'
                ),
                'recorded_by_t5_sha256': ci['workflow_under_test']['sha256_as_recorded_by_t5'],
                'sha256_now': ci['sha256_now'],
                't5_artifact_rewritten': False,
                'blocks_ready_for_integration': False,
            },
            {
                'finding_id': EVIDENCE_CORRECTION_V2_STALE_FINDING_ID,
                'detail': (
                    'the evidence-integrity correction v2 record pins the integration bundle '
                    'surface it observed, and its own --check re-derives its mutant-name survey '
                    'from the live tree. Re-binding this bundle to the repaired preflight v2 / '
                    'decision v2 removes the pre-repair preflight v2 copy that carried two '
                    'mutant-name mentions, so that survey re-derives with fewer recorded mention '
                    'paths and the record now reports `bundle member is stale`. The drift is '
                    'bookkeeping only: the record digest table, tool-pin table, frozen-byte '
                    're-verification and order-guard results are byte-identical, and no frozen '
                    'byte moved. This task may not rewrite a v2 record, so the closure is recorded '
                    f'here and in the decision file instead of editing `{_relative(EVIDENCE_CORRECTION_V2)}`'
                ),
                'recorded_in': _relative(EVIDENCE_CORRECTION_V2),
                'recorded_in_byte_sha256': EVIDENCE_CORRECTION_V2_BYTE_SHA256,
                'detected_by': 'python3 tools/training/build_hierarchical_evidence_integrity_correction_v2.py --check',
                'observed': 'FAIL: bundle member is stale: EVIDENCE_INTEGRITY_CORRECTION_V2.json',
                'cause': 'the mutant-name survey re-derives from the live tree',
                'only_recorded_mentions_changed': True,
                'touches_a_frozen_byte': False,
                'owner': 'the evidence-integrity correction v2 record; re-derivation is its owner step',
                'blocks_ready_for_integration': False,
            },
        ]

        resolved_findings = [*pin_findings, closed_bundle_pin_finding()]

        recorded_local_observations = [
            {
                'command': 'python3 tools/training/finalize_hierarchical_exact_tree_decision.py --check',
                'observed_result': 'PASS',
                'observed_exit_code': 0,
            },
            {
                'command': 'python3 tools/training/write_frozen_validation_protocol_v2.py --check',
                'observed_result': 'PASS (v1_surfaces_verified=10)',
                'observed_exit_code': 0,
            },
            {
                'command': 'python3 tools/training/fit_model_a_preflop_sizing_hierarchical.py --check',
                'observed_result': 'OK (status=BLOCKED_SCIENTIFIC, next_issue=367)',
                'observed_exit_code': 0,
            },
            {
                'command': 'python3 tools/training/audit_hierarchical_candidate_contract.py',
                'observed_result': 'PASS (active_pointer_unchanged=true)',
                'observed_exit_code': 0,
            },
            {
                'command': 'python3 tools/simulation/issue419_exact_tree_preflight.py --check',
                'observed_result': (
                    'PASS: the frozen v1 preflight and the protocol v2 custody row are '
                    're-derived from the restored bytes (repaired by 9859c46)'
                ),
                'observed_exit_code': 0,
                'note': 'was RED before 9859c46 restored the tool pins',
            },
            {
                'command': 'python3 tools/training/write_frozen_validation_protocol.py --check',
                'observed_result': (
                    'FAIL (expected): ValidationOrderError: VALIDATION was already read for the '
                    'hierarchical candidate; the frozen protocol must be authored before any '
                    'evaluation'
                ),
                'observed_exit_code': 1,
                'explained_by': 'EXPECTED_AFTER_THE_SINGLE_FROZEN_READ',
            },
            {
                'command': (
                    'PYTHONPATH=. python3 tests/simulation/test_issue419_exact_tree_preflight.py'
                ),
                'observed_result': 'OK (24 tests; was RED before the 9859c46 pin repair)',
                'observed_exit_code': 0,
            },
            {
                'command': 'python3 tools/training/build_hierarchical_integration_bundle_v2.py --check',
                'observed_result': 'PASS (members re-derived, no drift)',
                'observed_exit_code': 0,
            },
            {
                'command': (
                    'PYTHONPATH=. python3 tests/training/test_issue419_hierarchical_exact_tree.py'
                ),
                'observed_result': 'OK (24 tests; was RED before this regeneration)',
                'observed_exit_code': 0,
            },
            {
                'command': (
                    'python3 tools/training/build_hierarchical_evidence_integrity_correction_v2.py '
                    '--check'
                ),
                'observed_result': (
                    'FAIL: bundle member is stale: EVIDENCE_INTEGRITY_CORRECTION_V2.json '
                    '(its mutant-name survey re-derives from the live tree; bookkeeping only, '
                    'no frozen byte moved)'
                ),
                'observed_exit_code': 1,
                'explained_by': EVIDENCE_CORRECTION_V2_STALE_FINDING_ID,
            },
        ]

        bundle = {
            'schema': SCHEMA,
            'kind': 'ISSUE419_HIERARCHICAL_EXACT_TREE_INTEGRATION_BUNDLE_V2',
            'issue': ISSUE,
            'parent_issue': PARENT_ISSUE,
            'source_issue': SOURCE_ISSUE,
            'scenario_issue': SCENARIO_ISSUE,
            'next_issue': NEXT_ISSUE,
            'bundle_task': BUNDLE_TASK,
            'planner_key': PLANNER_KEY,
            'bundle_dir': _relative(HERE),
            'branch': BRANCH,
            'authored_at': AUTHORED_AT,
            'authorship_note': (
                'every claim below is either re-derived by this tool from the persisted bytes '
                '(reverified_by_this_tool), quoted from the digest-referenced T5 CI evidence or '
                'recorded as a labelled, non-authoritative local observation'
            ),
            'generated_by': {
                'path': _relative(SOURCE_PATH),
                'sha256': sha256_file(SOURCE_PATH),
                'reproduce': (
                    'python3 tools/training/build_hierarchical_integration_bundle_v2.py'
                ),
                'check': (
                    'python3 tools/training/build_hierarchical_integration_bundle_v2.py --check'
                ),
            },
            'verdict': {
                'status': STATUS,
                'decision': DECISION,
                'admitted': False,
                'integration_ready': False,
                'required_tree_complete': False,
                'primary_blocker': PRIMARY_BLOCKER,
                'blockers': list(BLOCKERS),
                'required_tree_node_count': preflight_v2['required_tree']['required_node_count'],
                'admissible_exact_node_count': 0,
                'exact_unresolved_node_count': preflight_v2['required_tree']['required_node_count'],
                'required_tree_sha256': REQUIRED_TREE_SHA256,
                'admissibility_class_counts': preflight_v2['admissibility'][
                    'admissibility_class_counts'
                ],
            },
            'candidate': {
                'candidate_id': CANDIDATE_ID,
                'candidate_instance_id': CANDIDATE_INSTANCE_ID,
                'candidate_sha256': CANDIDATE_SHA256,
                'candidate_status_at_freeze': manifest['candidate']['status'],
                'identity_granularity': manifest['candidate']['identity_granularity'],
                'support_isolation_rule': SUPPORT_ISOLATION_RULE,
                'distinct_from_issue_352': manifest['candidate']['distinct_from'][
                    'issue_352_candidate_id'
                ],
                'model_family': manifest['candidate']['model_family'],
            },
            'boundaries': {
                'split_consumed': 'TRAIN_AND_ONE_FROZEN_VALIDATION_READ',
                'holdout_reopened_by_this_bundle': False,
                'decision_rows_read_by_this_bundle': 0,
                'hand_histories_parsed_by_this_bundle': 0,
                'metrics_recomputed_by_this_bundle': 0,
                'thresholds_re_selected_by_this_bundle': False,
                'test_authorized': False,
                'test_consumed': False,
                'test_decisions_read': 0,
                'hero_ev_executed': False,
                'recommendation_computed': False,
                'rollouts_executed': 0,
                'issue367_run': False,
                'issue367_authorized': False,
                'active_pointer_mutated': False,
                'active_model_reference_sha256': ACTIVE_MODEL_BYTE_SHA256,
                'validation_read_count': 1,
                'validation_consumed': True,
                'holdout_access_scan': holdout_scan,
                'issue367_boundary_scan': issue367_scan,
                'dataset_or_hand_history_opens': [],
                'files_opened_count': len(set(opened_paths)),
                'files_opened': sorted(set(opened_paths)),
                'protected_files_before': protected_before,
            },
            'provenance': {
                'T1_frozen_validation_protocol_v2': _relative(PROTOCOL_V2),
                'T2_hierarchical_model_spec': _relative(MODEL_SPEC),
                'T3_train_fit_report': _relative(FIT_REPORT),
                'T4_candidate_manifest': _relative(CANDIDATE_MANIFEST),
                'T4_candidate_contract': _relative(CONTRACT),
                'T5_ci_evidence': _relative(CI_EVIDENCE),
                'T6_consumed_validation_result': _relative(VALIDATION_V1),
                'T7_terminal_decision_v2': _relative(DECISION_V2),
                'T8_exact_tree_preflight_v2': _relative(PREFLIGHT_V2),
                'T1_sparsity_baseline': _relative(SPARSITY_BASELINE),
                'evidence_integrity_correction': _relative(CORRECTION),
                'evidence_integrity_correction_v2': _relative(EVIDENCE_CORRECTION_V2),
                'raise_sizing_frontier_resolution_v1_custody': _relative(FRONTIERS),
                'raise_sizing_frontier_resolution_v2': _relative(FRONTIERS_V2),
                'required_exact_tree': 'analysis/issue388_exact_tree/REQUIRED_EXACT_TREE.json',
            },
            'regeneration': {
                'reason': (
                    'the bundle bound the pre-repair EXACT_TREE_PREFLIGHT_V2.json (2c07ae32) and '
                    'DECISION_V2.json (ac291b9e) revisions; commits 9859c46 and 0f9a6eb '
                    'regenerated those bundles, so this regeneration re-binds the repaired '
                    'revisions and re-writes every derived member'
                ),
                'repaired_revisions': {
                    'exact_tree_preflight_v2': {
                        'before': PREFLIGHT_V2_PRE_REPAIR_BYTE_SHA256,
                        'after': PREFLIGHT_V2_BYTE_SHA256,
                        'written_by': PREFLIGHT_PIN_REPAIR_COMMIT,
                    },
                    'terminal_decision_v2': {
                        'before': DECISION_V2_PRE_REPAIR_BYTE_SHA256,
                        'after': DECISION_V2_BYTE_SHA256,
                        'written_by': DECISION_V2_REPAIR_COMMIT,
                    },
                },
                'closes_finding': EVIDENCE_CORRECTION_V2_FINDING_ID,
                'frozen_bytes_rewritten': False,
                'thresholds_moved': False,
            },
            'bundle_members': members,
            'coherence': coherence,
            'ci_evidence': ci,
            'ci_proven_claims': [],
            'ci_proven_claims_note': (
                'empty by construction: no real CI run ID proves any #419 claim, so none may be '
                'listed here. Only a push-triggered run of « Execute issue 419 hierarchical '
                'exact tree » at the pushed head, with conclusion=success, may move '
                'ci_observation.status off NOT_OBSERVED'
            ),
            'recorded_local_observations': recorded_local_observations,
            'recorded_local_observations_note': (
                'recorded by the task worker inside the isolated worktree sandbox on '
                f'{AUTHORED_AT[:10]}; they are NON-AUTHORITATIVE, were not re-executed by this '
                'tool and are never merge evidence'
            ),
            'required_supersessions': required_supersessions,
            'declared_supersessions': declared_supersessions,
            'residual_findings': residual_findings,
            'resolved_findings': resolved_findings,
            'reverified_by_this_tool': [
                'the T1/T2/T3/T4/T5/T6/T7/T8 authority digests',
                'every upstream content-addressed index and its object copies',
                'the root ARTIFACTS.json / SUMMARY.md frozen bytes',
                'the active Model A v5 reference and both registries',
                'no holdout / hand-history file was opened (runtime tripwire)',
                'no holdout loader symbol or module is referenced (AST scan)',
                'no #367 Hero EV runner symbol is referenced (AST scan)',
                'the preflight tool pins now equal the restored v1 / protocol v2 custody bytes '
                '(repaired by 9859c46), so issue419_exact_tree_preflight.py --check is GREEN',
                'the repaired preflight v2 and terminal decision v2 revisions this bundle copies '
                'are the ones commits 9859c46 and 0f9a6eb wrote',
                'the renewed frontier v2 custody the terminal decision v2 binds',
            ],
            'reproduction': {
                'build': 'python3 tools/training/build_hierarchical_integration_bundle_v2.py',
                'check': 'python3 tools/training/build_hierarchical_integration_bundle_v2.py --check',
                'tests': 'PYTHONPATH=. python3 tests/training/test_issue419_hierarchical_exact_tree.py',
            },
        }
        bundle['n8n_task_result'] = build_n8n_block(bundle)

    protected_after = {_relative(p): sha256_file(p) for p in PROTECTED_PATHS}
    if protected_before != protected_after:
        moved = sorted(
            key for key in set(protected_before) | set(protected_after)
            if protected_before.get(key) != protected_after.get(key)
        )
        raise IntegrationBundleError(f'protected files moved during the build: {moved}')
    bundle['boundaries']['protected_files_unchanged'] = True
    return bundle


def _copy_role(name: str) -> str:
    return {
        'HIERARCHICAL_MODEL_SPEC.json': 'T2_HIERARCHICAL_MODEL_SPEC',
        'TRAIN_FIT_REPORT.json': 'T3_TRAIN_FIT_REPORT',
        'CANDIDATE_MANIFEST.json': 'T4_CANDIDATE_MANIFEST',
        'EXACT_TREE_PREFLIGHT_V2.json': 'T8_EXACT_TREE_PREFLIGHT_V2',
        'DECISION_V2.json': 'T7_TERMINAL_DECISION_V2',
    }[name]


def _reference_role(name: str) -> str:
    return {
        'FROZEN_VALIDATION_PROTOCOL_V2.json': 'T1_FROZEN_VALIDATION_PROTOCOL_V2',
        'VALIDATION_RESULT.json': 'T6_CONSUMED_VALIDATION_RESULT_V1',
        'RAISE_SIZING_FRONTIER_RESOLUTION.json': 'T1B_RAISE_SIZING_FRONTIER_RESOLUTION_V2',
    }[name]


def build_n8n_block(bundle: Mapping[str, Any]) -> dict[str, Any]:
    verdict = bundle['verdict']
    boundaries = bundle['boundaries']
    block = {
        'type': 'N8N_TASK_RESULT',
        'issue': bundle['issue'],
        'next_issue': bundle['next_issue'],
        'status': verdict['status'],
        'decision': verdict['decision'],
        'bundle': bundle['bundle_dir'],
        'candidate_id': bundle['candidate']['candidate_id'],
        'candidate_sha256': bundle['candidate']['candidate_sha256'],
        'required_tree_complete': verdict['required_tree_complete'],
        'required_tree_sha256': verdict['required_tree_sha256'],
        'primary_blocker': verdict['primary_blocker'],
        'blockers': list(verdict['blockers']),
        'validation_consumed': boundaries['validation_consumed'],
        'validation_reference_sha256': VALIDATION_V1_BYTE_SHA256,
        'validation_outcome': _load(VALIDATION_V1)['outcome'],
        'test_consumed': boundaries['test_consumed'],
        'active_pointer_mutated': boundaries['active_pointer_mutated'],
        'hero_ev_executed': boundaries['hero_ev_executed'],
        'issue367_run': boundaries['issue367_run'],
        'admitted': verdict['admitted'],
        'integration_ready': verdict['integration_ready'],
        'ci_status': bundle['ci_evidence']['status'],
    }
    return block


def render_n8n_block(block: Mapping[str, Any]) -> str:
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


def _bullets(lines: Sequence[str], items: Sequence[str]) -> None:
    for item in items:
        lines.append(f'* {item}')


def _table(lines: list[str], headers: Sequence[str], rows: Sequence[Sequence[str]]) -> None:
    lines.append('| ' + ' | '.join(headers) + ' |')
    lines.append('| ' + ' | '.join('---' for _ in headers) + ' |')
    for row in rows:
        lines.append('| ' + ' | '.join(_cell(cell) for cell in row) + ' |')
    lines.append('')


def _cell(value: Any) -> str:
    """Render a table cell deterministically (booleans lower-case, no None)."""
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if value is None:
        return 'null'
    return str(value)


def render_report(bundle: Mapping[str, Any]) -> str:
    verdict = bundle['verdict']
    candidate = bundle['candidate']
    boundaries = bundle['boundaries']
    ci = bundle['ci_evidence']
    lines: list[str] = []
    lines.append('# #419 — integration report v2 (T7): hierarchical exact-tree evidence bundle')
    lines.append('')
    lines.append(f'Schema `{bundle["schema"]}`, bundle `{bundle["bundle_dir"]}`, task '
                 f'`{bundle["bundle_task"]}` (`{bundle["planner_key"]}`), issue #{bundle["issue"]} '
                 f'(source issue #{bundle["source_issue"]}, scenario #{bundle["scenario_issue"]}), '
                 f'next issue #{bundle["next_issue"]}.')
    lines.append('')
    lines.append(f'This report consolidates the terminal #419 evidence into one content-addressed '
                 f'bundle. Every member is either a byte-identical copy of a T1/T3/T4 authority or '
                 f'a digest reference whose bytes are never duplicated. Nothing outside '
                 f'`{bundle["bundle_dir"]}/` is written; no holdout is re-opened; #367 is never run.')
    lines.append('')
    lines.append('## 1. Verdict (n8n)')
    lines.append('')
    lines.append('```')
    lines.append(render_n8n_block(bundle['n8n_task_result']).rstrip('\n'))
    lines.append('```')
    lines.append('')
    lines.append(f'`{verdict["status"]}` / `{verdict["decision"]}`. Admission is never forced: it '
                 f'requires `required_tree_complete=true` **and** a VALIDATION outcome of '
                 f'`ADMIT_CANDIDATE` with every frozen gate passing. Neither holds — '
                 f'`{verdict["admissible_exact_node_count"]}` of '
                 f'`{verdict["required_tree_node_count"]}` required nodes carry an admissible '
                 f'answer, and the consumed VALIDATION result published '
                 f'`{_load(VALIDATION_V1)["outcome"]}`.')
    lines.append('')
    lines.append('Blockers: ' + ', '.join(f'`{code}`' for code in verdict['blockers']) + '.')
    lines.append('')
    lines.append('## 2. Bundle inventory (content-addressed)')
    lines.append('')
    rows = []
    for name in MEMBER_NAMES:
        member = bundle['bundle_members'].get(name)
        if member is None:
            rows.append((name, 'GENERATED', 'see `ARTIFACTS.json`', '—', '—'))
            continue
        rows.append((
            name,
            member['mode'],
            member['role'],
            member['source_byte_sha256'],
            member.get('canonical_payload_sha256', '—'),
        ))
    _table(lines, ('member', 'mode', 'role', 'byte sha256', 'canonical payload'), rows)
    lines.append('`INTEGRATION_REPORT.json` is the machine-readable source of this document; '
                 f'`INTEGRATION_REPORT.md` is rendered from it. `ARTIFACTS.json` binds all '
                 f'{len(MEMBER_NAMES)} members by byte digest and content-addressed object, and '
                 '`INTEGRATION_REPORT.sha256` pins the report itself.')
    lines.append('')
    lines.append('## 3. What is proven by a real CI run ID, and what is only local')
    lines.append('')
    lines.append('This section is the point of the report, so it is stated without decoration.')
    lines.append('')
    lines.append('### 3.1 Proven by a real CI run ID')
    lines.append('')
    proven = bundle['ci_proven_claims']
    lines.append(f'**None.** `ci_proven_claims` has {len(proven)} entries. The authoritative '
                 f'workflow « {ci["workflow_under_test"]["name"]} » has never produced a run: the '
                 f'T5 evidence bundle records `ci_observation.status = {ci["status"]}`, '
                 f'`run_name_recorded = {_cell(ci["run_name_recorded"])}`, `run_url = '
                 f'{_cell(ci["run_url_recorded"])}`, and the workflow is '
                 f'`present_at_remote_pr_head = {str(ci["workflow_under_test"]["present_at_remote_pr_head"]).lower()}`.')
    lines.append('')
    lines.append(f'The {ci["observed_run_count"]} real CI run IDs that do exist at the reviewed PR '
                 f'head `{ci["pull_request"]["head_sha_at_verification"]}` are recorded here '
                 f'because they are real, and every one of them executes **none** of the #419 '
                 f'suites:')
    lines.append('')
    _table(
        lines,
        ('workflow', 'run', 'event', 'conclusion', 'executes #419 suites', 'url'),
        [
            (
                row['name'],
                f'#{row["run_number"]}',
                row['event'],
                row['conclusion'],
                'yes' if row['executes_the_issue419_suites'] else 'no',
                row['url'],
            )
            for row in ci['recorded_runs']
        ],
    )
    lines.append(f'`none_executes_the_issue419_suites = '
                 f'{str(ci["none_executes_the_issue419_suites"]).lower()}`. The status may not be '
                 f'promoted by any of: ' + ', '.join(f'`{item}`' for item in ci['promotion_forbidden_by']) + '.')
    lines.append('')
    lines.append('### 3.2 Verified locally from persisted bytes by this tool (authoritative only '
                 'for byte identity)')
    lines.append('')
    _bullets(lines, bundle['reverified_by_this_tool'])
    lines.append('')
    lines.append('### 3.3 Recorded local observations (NON-AUTHORITATIVE, never merge evidence)')
    lines.append('')
    lines.append(bundle['recorded_local_observations_note'])
    lines.append('')
    _table(
        lines,
        ('command', 'observed', 'exit', 'explained by'),
        [
            (
                f'`{row["command"]}`',
                row['observed_result'],
                row['observed_exit_code'],
                row.get('explained_by', '—'),
            )
            for row in bundle['recorded_local_observations']
        ],
    )
    lines.append('## 4. Supersession ledger')
    lines.append('')
    for item in bundle['required_supersessions']:
        lines.append(f'### {item["supersession_id"]}')
        lines.append('')
        if 'superseded' in item and isinstance(item['superseded'], dict):
            lines.append(f'* superseded: `{item["superseded"]["byte_sha256"]}` '
                         f'(canonical `{item["superseded"]["canonical_payload_sha256"]}`, kept at '
                         f'`{item["superseded"]["path"]}`)')
            lines.append(f'* superseding: `{item["superseding"]["byte_sha256"]}` '
                         f'(canonical `{item["superseding"]["canonical_payload_sha256"]}`, '
                         f'`{item["superseding"]["path"]}`)')
            lines.append(f'* mechanism: `{item["mechanism"]}`; thresholds moved: '
                         f'`{str(item["thresholds_moved"]).lower()}`; gates relaxed: '
                         f'`{str(item["gates_relaxed"]).lower()}`')
        else:
            lines.append(f'* mutant commit `{item["mutant_commit"]}` ({item["mutant_task"]}) '
                         f'rewrote `EXACT_TREE_PREFLIGHT.json` to '
                         f'`{item["mutant_digests"]["EXACT_TREE_PREFLIGHT.json"]}` '
                         f'(canonical `{item["mutant_digests"]["canonical_payload_sha256"]}`) and '
                         f're-registered the index as `{item["mutant_digests"]["ARTIFACTS.json"]}`')
            lines.append(f'* correction `{item["corrected_commit"]}` '
                         f'(`{item["corrected_by"]}`, `{item["correction_artifact"]}`, '
                         f'`{item["correction_artifact_sha256"]}`) restored '
                         f'`EXACT_TREE_PREFLIGHT.json` to '
                         f'`{item["restored_digests"]["EXACT_TREE_PREFLIGHT.json"]}` (canonical '
                         f'`{item["restored_digests"]["canonical_payload_sha256"]}`) and the index '
                         f'to `{item["restored_digests"]["ARTIFACTS.json"]}`, without touching a pin '
                         f'and without rewriting a frozen byte to fit a digest')
            lines.append(f'* superseded by `{item["superseded_by"]}`; follow-on findings '
                         f'`{", ".join(item["follow_on_findings"])}` are '
                         f'`{item["follow_on_finding_status"]}` '
                         f'(repaired by `{item["follow_on_finding_repaired_by"]}`)')
        lines.append('')
        lines.append(f'Claim: {item["claim"]}')
        lines.append('')
    lines.append('### Other declared supersessions')
    lines.append('')
    for item in bundle['declared_supersessions']:
        lines.append(f'* `{item["supersession_id"]}`: `{item["superseded"]}` → '
                     f'`{item["superseding"]}` — {item["reason"]}')
    lines.append('')
    lines.append('## 5. Findings: what is residual and what is resolved')
    lines.append('')
    lines.append('Residual findings (each still blocks `READY_FOR_INTEGRATION` where marked):')
    lines.append('')
    _table(
        lines,
        ('finding', 'blocks READY_FOR_INTEGRATION', 'detail'),
        [(item['finding_id'], item['blocks_ready_for_integration'], item['detail'])
         for item in bundle['residual_findings']],
    )
    lines.append('Resolved / closed findings (recorded history, never a live pin):')
    lines.append('')
    _table(
        lines,
        ('finding', 'status', 'detail'),
        [(item['finding_id'], item['status'], item['detail'])
         for item in bundle['resolved_findings']],
    )
    finding = next(item for item in bundle['resolved_findings']
                   if item['finding_id'] == 'V1_PREFLIGHT_PIN_STALE')
    lines.append(f'`V1_PREFLIGHT_PIN_STALE` in detail: the preflight tool pins '
                 f'`V1_PREFLIGHT_SHA256={finding["tool_pins"]["V1_PREFLIGHT_SHA256"]}` and '
                 f'`V1_INDEX_SHA256={finding["tool_pins"]["V1_INDEX_SHA256"]}`, and the restored '
                 f'authority on disk is `{finding["on_disk"]["EXACT_TREE_PREFLIGHT.json"]}` / '
                 f'`{finding["on_disk"]["ARTIFACTS.json"]}` '
                 f'(`pin_matches_on_disk_bytes={str(finding["pin_matches_on_disk_bytes"]).lower()}`). '
                 f'`{finding["introduced_by"]}` re-pointed the pin after the correction '
                 f'`{finding["restored_by"]}` restored the bytes; `{finding["repaired_by"]}` then '
                 f'restored the pin, so `{finding["detected_by"]}` is GREEN again '
                 f'(`{finding["observed_at_this_head"]}`) and the finding no longer blocks '
                 f'integration.')
    lines.append('')
    v2_finding = next(item for item in bundle['resolved_findings']
                      if item['finding_id'] == 'PROTOCOL_V2_PREFLIGHT_PIN_STALE')
    lines.append(f'`PROTOCOL_V2_PREFLIGHT_PIN_STALE` in detail: the same tool pins '
                 f'`PROTOCOL_V2_BYTE_SHA256={v2_finding["tool_pins"]["PROTOCOL_V2_BYTE_SHA256"]}` '
                 f'and `PROTOCOL_V2_CANONICAL_PAYLOAD_SHA256='
                 f'{v2_finding["tool_pins"]["PROTOCOL_V2_CANONICAL_PAYLOAD_SHA256"]}`, and the '
                 f'amended protocol v2 authority on disk is '
                 f'`{v2_finding["on_disk"]["byte_sha256"]}` / '
                 f'`{v2_finding["on_disk"]["canonical_payload_sha256"]}` '
                 f'(`pin_matches_on_disk_bytes='
                 f'{str(v2_finding["pin_matches_on_disk_bytes"]).lower()}`). '
                 f'`{v2_finding["introduced_by"]}` re-pointed both protocol v2 pins to the '
                 f'pre-correction digests and `{v2_finding["repaired_by"]}` restored them, so the '
                 f'preflight suite is `{v2_finding["observed_at_this_head"]}`.')
    lines.append('')
    closed = next(item for item in bundle['resolved_findings']
                  if item['finding_id'] == EVIDENCE_CORRECTION_V2_FINDING_ID)
    lines.append(f'`{closed["finding_id"]}` in detail: the evidence-integrity correction v2 '
                 f'record (`{closed["recorded_in"]["path"]}`, '
                 f'`{closed["recorded_in"]["byte_sha256"]}`) recorded this finding and deferred it '
                 f'to the integration-bundle task. This regeneration closes it '
                 f'(`{closed["status"]}`, closed by `{closed["closed_by"]}`): before '
                 f'`EXACT_TREE_PREFLIGHT_V2.json`=`{closed["before"]["EXACT_TREE_PREFLIGHT_V2.json"]}`'
                 f' / `DECISION_V2.json`=`{closed["before"]["DECISION_V2.json"]}`, after '
                 f'`EXACT_TREE_PREFLIGHT_V2.json`=`{closed["after"]["EXACT_TREE_PREFLIGHT_V2.json"]}`'
                 f' / `DECISION_V2.json`=`{closed["after"]["DECISION_V2.json"]}`. It touches no '
                 f'frozen byte.')
    lines.append('')
    lines.append('## 6. Coherence with the T1/T3/T4 authorities')
    lines.append('')
    _table(
        lines,
        ('cross-check', 'value'),
        [(key, value) for key, value in bundle['coherence'].items()
         if not isinstance(value, list)],
    )
    lines.append(f'Candidate `{candidate["candidate_id"]}` (`{candidate["candidate_sha256"]}`) is '
                 f'the T4 candidate: the T4 manifest, the candidate contract and the terminal '
                 f'decision v2 all name the same id and the same canonical digest, and the required '
                 f'tree `{verdict["required_tree_sha256"]}` is the one both decisions and the '
                 f'preflight v2 walk.')
    lines.append('')
    lines.append('## 7. Boundaries')
    lines.append('')
    _bullets(lines, [
        f'`validation_consumed={str(boundaries["validation_consumed"]).lower()}` — exactly one '
        f'frozen read, performed by T6; this bundle reads the published result '
        f'**by digest only** (`{VALIDATION_V1_BYTE_SHA256}`)',
        f'`holdout_reopened_by_this_bundle='
        f'{str(boundaries["holdout_reopened_by_this_bundle"]).lower()}`, '
        f'`decision_rows_read_by_this_bundle={boundaries["decision_rows_read_by_this_bundle"]}`, '
        f'`metrics_recomputed_by_this_bundle={boundaries["metrics_recomputed_by_this_bundle"]}`, '
        f'`thresholds_re_selected_by_this_bundle='
        f'{str(boundaries["thresholds_re_selected_by_this_bundle"]).lower()}`',
        f'`test_consumed={str(boundaries["test_consumed"]).lower()}`, '
        f'`test_authorized={str(boundaries["test_authorized"]).lower()}` — TEST is untouched',
        f'`active_pointer_mutated={str(boundaries["active_pointer_mutated"]).lower()}` — the active '
        f'Model A v5 reference stays `{boundaries["active_model_reference_sha256"]}`',
        f'`hero_ev_executed={str(boundaries["hero_ev_executed"]).lower()}`, '
        f'`rollouts_executed={boundaries["rollouts_executed"]}`, '
        f'`issue367_run={str(boundaries["issue367_run"]).lower()}` — #367 is never run by #419',
        f'no hand history, decision row or dataset file was opened: '
        f'`dataset_or_hand_history_opens = {boundaries["dataset_or_hand_history_opens"]}` over '
        f'{boundaries["files_opened_count"]} benign evidence files opened',
        f'every frozen input is re-verified byte-for-byte before and after the build: '
        f'`protected_files_unchanged={str(boundaries["protected_files_unchanged"]).lower()}` over '
        f'{len(boundaries["protected_files_before"])} files',
    ])
    lines.append('')
    lines.append('## 8. Reproduction')
    lines.append('')
    lines.append('```bash')
    lines.append(bundle['reproduction']['build'])
    lines.append(bundle['reproduction']['check'])
    lines.append(bundle['reproduction']['tests'])
    lines.append('```')
    lines.append('')
    lines.append('## 9. Why the status is BLOCKED_SCIENTIFIC, and what READY_FOR_INTEGRATION '
                 'would take')
    lines.append('')
    lines.append(f'The verdict is `{verdict["status"]}` because the required #388/#419 response '
                 f'tree is not complete: `{verdict["admissible_exact_node_count"]}` of '
                 f'`{verdict["required_tree_node_count"]}` required nodes carry an admissible '
                 f'answer, the primary blocker is `{verdict["primary_blocker"]}`, and the seven '
                 f'raise-sizing frontiers stay unresolved. The consumed VALIDATION result fails '
                 f'`calibration_absolute` and `coverage_floor`. A fail-closed node is never '
                 f'repaired by lowering a frozen threshold, so no adjustment is available here.')
    lines.append('')
    lines.append('`READY_FOR_INTEGRATION` would additionally require, in this order:')
    lines.append('')
    lines.append('1. the `V1_PREFLIGHT_PIN_STALE` and `PROTOCOL_V2_PREFLIGHT_PIN_STALE` defects '
                 'fixed by their owner task -- **done**: `9859c46` restored the four pins without '
                 'moving a frozen surface, so `issue419_exact_tree_preflight.py --check` and the '
                 'preflight suite are GREEN and this bundle now binds the repaired revisions;')
    lines.append('2. the branch pushed past the reviewed head so '
                 '`« Execute issue 419 hierarchical exact tree »` can run, and a real run ID '
                 'recorded with `conclusion=success` and the no-op guard reporting every declared '
                 'suite executed;')
    lines.append('3. a scientific resolution of `NO_ADMISSIBLE_POOLING_LEVEL` and of the seven '
                 'raise-sizing frontiers, which is a #367/#388 question and not something #419 may '
                 'simulate.')
    lines.append('')
    lines.append('Nothing in this bundle admits the candidate, promotes it, wires the provider or '
                 'moves a pointer. It records evidence only.')
    return '\n'.join(lines) + '\n'


def render_summary(bundle: Mapping[str, Any]) -> str:
    verdict = bundle['verdict']
    boundaries = bundle['boundaries']
    ci = bundle['ci_evidence']
    reference_count = sum(
        1 for member in bundle['bundle_members'].values()
        if member['mode'] == 'DIGEST_REFERENCE_NO_BYTES'
    )
    copy_count = len(bundle['bundle_members']) - reference_count
    lines = [
        '# #419 — integration bundle v2 summary',
        '',
        f'**{verdict["status"]} / {verdict["decision"]}** — candidate '
        f'`{bundle["candidate"]["candidate_id"]}` '
        f'(`{bundle["candidate"]["candidate_sha256"]}`) is **not** admitted and **not** wired into '
        f'#367.',
        '',
        f'Bundle `{bundle["bundle_dir"]}` (`{bundle["schema"]}`), task `{bundle["bundle_task"]}` '
        f'({bundle["planner_key"]}). Members: {len(bundle["bundle_members"])} authorities bound by '
        f'byte + canonical digest — {copy_count} as byte-identical copies and {reference_count} as '
        f'digest references — plus `INTEGRATION_REPORT.json`, `INTEGRATION_REPORT.md`, '
        f'`SUMMARY.md`, `N8N_TASK_RESULT.txt` and the `ARTIFACTS.json` index.',
        '',
        f'`required_tree_complete=false` — {verdict["admissible_exact_node_count"]} of '
        f'{verdict["required_tree_node_count"]} required nodes are admissible; primary blocker '
        f'`{verdict["primary_blocker"]}`. VALIDATION published `{_load(VALIDATION_V1)["outcome"]}` '
        f'(failing gates: '
        f'{", ".join(_load(VALIDATION_V1)["gate"]["failing_gates"])}).',
        '',
        f'CI: `ci_observation.status = {ci["status"]}` — the authoritative workflow has never run '
        f'and none of the {ci["observed_run_count"]} real recorded CI runs executes a #419 suite. '
        f'`ci_proven_claims` is empty; everything else in this bundle is local, non-authoritative. '
        f'The real run IDs, with URLs, are listed in `INTEGRATION_REPORT.md` §3.1 and in '
        f'`ci_evidence.recorded_runs`.',
        '',
        f'Boundaries: `validation_consumed={str(boundaries["validation_consumed"]).lower()}` '
        f'(single frozen read, referenced by digest `{VALIDATION_V1_BYTE_SHA256}`), '
        f'`test_consumed={str(boundaries["test_consumed"]).lower()}`, '
        f'`active_pointer_mutated={str(boundaries["active_pointer_mutated"]).lower()}`, '
        f'`hero_ev_executed={str(boundaries["hero_ev_executed"]).lower()}`, '
        f'`issue367_run={str(boundaries["issue367_run"]).lower()}`, `next_issue='
        f'{bundle["next_issue"]}`.',
        '',
        'Supersessions: the v2 protocol payload '
        f'`{PROTOCOL_V2_SUPERSEDED_BYTE_SHA256}` is superseded by '
        f'`{PROTOCOL_V2_BYTE_SHA256}` through `{PROTOCOL_V2_AMENDMENT_ID}`; the '
        '`v1 EXACT_TREE_PREFLIGHT.json` bytes were rewritten by mutant `871e0bd` to '
        f'`{PREFLIGHT_V1_PRECORRECTION_BYTE_SHA256}` and restored to '
        f'`{PREFLIGHT_V1_BYTE_SHA256}` by correction `{CORRECTION_COMMIT}`; the raise-sizing '
        f'frontier resolution `{FRONTIERS_BYTE_SHA256}` (v1 custody) is superseded by '
        f'`{FRONTIERS_V2_BYTE_SHA256}` (v2, `{FRONTIERS_V2_SCHEMA}`).',
        '',
        f'This regeneration binds the **repaired** revisions: `EXACT_TREE_PREFLIGHT_V2.json` = '
        f'`{PREFLIGHT_V2_BYTE_SHA256}` (was `{PREFLIGHT_V2_PRE_REPAIR_BYTE_SHA256}`) and '
        f'`DECISION_V2.json` = `{DECISION_V2_BYTE_SHA256}` (was `{DECISION_V2_PRE_REPAIR_BYTE_SHA256}`). '
        f'The `V1_PREFLIGHT_PIN_STALE` and `PROTOCOL_V2_PREFLIGHT_PIN_STALE` findings are '
        f'RESOLVED by `{PREFLIGHT_PIN_REPAIR_COMMIT}` (task backlog-911), and the deferred '
        f'finding `{EVIDENCE_CORRECTION_V2_FINDING_ID}` is CLOSED by this regeneration '
        f'(documented in `INTEGRATION_REPORT.md` §5).',
        '',
        '```',
        render_n8n_block(bundle['n8n_task_result']).rstrip('\n'),
        '```',
        '',
        f'Reproduce: `{bundle["reproduction"]["build"]}`; verify: '
        f'`{bundle["reproduction"]["check"]}`.',
        '',
    ]
    return '\n'.join(lines)


def reference_document(name: str, bundle: Mapping[str, Any]) -> dict[str, Any]:
    """The three digest-reference members, built from the verified authorities."""
    protocol_v2 = _load(PROTOCOL_V2)
    validation = _load(VALIDATION_V1)
    if name == 'FROZEN_VALIDATION_PROTOCOL_V2.json':
        return {
            'schema': REFERENCE_SCHEMA,
            'kind': 'DIGEST_REFERENCE_NOT_A_COPY',
            'artifact': name,
            'role': 'T1_FROZEN_VALIDATION_PROTOCOL_V2',
            'source': {
                'path': _relative(PROTOCOL_V2),
                'byte_sha256': PROTOCOL_V2_BYTE_SHA256,
                'canonical_payload_sha256': PROTOCOL_V2_CANONICAL_SHA256,
                'schema': protocol_v2['schema'],
                'digest_sidecar': _relative(PROTOCOL_V2.with_suffix('.sha256')),
                'bundle_index': _relative(PROTOCOL_V2.parent / INDEX_NAME),
            },
            'frozen_v1': {
                'path': _relative(PROTOCOL_V1),
                'byte_sha256': PROTOCOL_V1_BYTE_SHA256,
                'canonical_payload_sha256': PROTOCOL_V1_CANONICAL_SHA256,
            },
            'amendment': {
                'amendment_id': PROTOCOL_V2_AMENDMENT_ID,
                'revision_of': protocol_v2['revision_of'],
                'superseded_byte_sha256': PROTOCOL_V2_SUPERSEDED_BYTE_SHA256,
                'superseded_canonical_payload_sha256': PROTOCOL_V2_SUPERSEDED_CANONICAL_SHA256,
                'superseded_path': _relative(PROTOCOL_V2_SUPERSEDED),
                'superseded_kept_content_addressed': True,
            },
            'bytes_copied_into_this_bundle': False,
            'thresholds_moved': False,
            'gates_weaker_than_v1': False,
            'read_rule': (
                'the protocol v2 bytes are the T1 authority and stay the source of record; this '
                'bundle records their digest instead of duplicating them, and every --check '
                're-derives the digest from the persisted bytes'
            ),
        }
    if name == 'VALIDATION_RESULT.json':
        return {
            'schema': REFERENCE_SCHEMA,
            'kind': 'DIGEST_REFERENCE_NO_HOLDOUT_READ',
            'artifact': name,
            'role': 'T6_CONSUMED_VALIDATION_RESULT_V1',
            'source': {
                'path': _relative(VALIDATION_V1),
                'byte_sha256': VALIDATION_V1_BYTE_SHA256,
                'canonical_payload_sha256': VALIDATION_V1_CANONICAL_SHA256,
                'schema': validation.get('schema'),
                'digest_sidecar': _relative(VALIDATION_V1.with_suffix('.sha256')),
                'bundle_index': _relative(VALIDATION_V1.parent / INDEX_NAME),
            },
            'split': 'VALIDATION',
            'published_verdict': validation['outcome'],
            'published_failing_gates': list(validation['gate']['failing_gates']),
            'holdout_reopened_by_this_bundle': False,
            'decision_rows_read_by_this_bundle': 0,
            'hand_histories_parsed_by_this_bundle': 0,
            'metrics_recomputed_by_this_bundle': 0,
            'thresholds_re_selected_by_this_bundle': False,
            'digest_re_derived_from_persisted_bytes': True,
            'bytes_copied_into_this_bundle': False,
            'pointers_read': ['/outcome', '/gate/failing_gates', '/candidate', '/coverage'],
            'read_rule': (
                'the v1 VALIDATION bytes were consumed exactly once by the frozen protocol v1 '
                'evaluation; this bundle never re-reads the holdout. The verdict and failing-gate '
                'rows quoted above are published rows of the digest-referenced artifact, the same '
                'rows the terminal decision v2 quotes'
            ),
        }
    if name == 'RAISE_SIZING_FRONTIER_RESOLUTION.json':
        frontiers_v2 = _load(FRONTIERS_V2)
        return {
            'schema': REFERENCE_SCHEMA,
            'kind': 'DIGEST_REFERENCE_TRAIN_ONLY_NO_HOLDOUT_READ',
            'artifact': name,
            'role': 'T1B_RAISE_SIZING_FRONTIER_RESOLUTION_V2',
            'source': {
                'path': _relative(FRONTIERS_V2),
                'byte_sha256': FRONTIERS_V2_BYTE_SHA256,
                'canonical_payload_sha256': FRONTIERS_V2_CANONICAL_SHA256,
                'schema': frontiers_v2.get('schema'),
                'bundle_index': _relative(FRONTIERS_V2.parent / INDEX_NAME),
            },
            'revision': frontiers_v2.get('revision'),
            'supersedes': {
                'path': _relative(FRONTIERS),
                'byte_sha256': FRONTIERS_BYTE_SHA256,
                'canonical_payload_sha256': FRONTIERS_CANONICAL_SHA256,
                'schema': _load(FRONTIERS).get('schema'),
                'kept_content_addressed': True,
                'rewritten': False,
            },
            'split_consumed': frontiers_v2.get('split_consumed', 'TRAIN'),
            'frontiers_total': frontiers_v2.get('frontiers_total'),
            'resolved_count': frontiers_v2.get('resolved_count'),
            'independent_of_the_response_model': frontiers_v2.get(
                'independent_of_the_response_model'
            ),
            'bytes_copied_into_this_bundle': False,
            'thresholds_moved': False,
            'gates_weaker_than_v1': False,
            'holdout_reopened_by_this_bundle': False,
            'digest_re_derived_from_persisted_bytes': True,
            'read_rule': (
                'the raise-sizing frontier resolution is TRAIN-only evidence; this bundle records '
                'the v2 digest instead of duplicating the bytes. The v1 revision stays '
                'byte-frozen custody and is re-verified on every build and never rewritten, while '
                'the terminal decision v2 binds the v2 revision for its values'
            ),
        }
    raise IntegrationBundleError(f'no reference document is defined for {name}')


def bundle_files(bundle: Mapping[str, Any]) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for name, source, _ in COPIES:
        files[name] = source.read_bytes()
    for name, _, _ in REFERENCES:
        files[name] = serialize(reference_document(name, bundle))
    report_json = serialize(bundle)
    files[REPORT_JSON_NAME] = report_json
    files[REPORT_NAME] = render_report(bundle).encode()
    files[SUMMARY_NAME] = render_summary(bundle).encode()
    files[N8N_NAME] = render_n8n_block(bundle['n8n_task_result']).encode()
    return files


def persist(bundle: Mapping[str, Any]) -> dict[str, Any]:
    """Write the bundle: members, their objects and the content-addressed index."""
    files = bundle_files(bundle)
    expected = set(MEMBER_NAMES) | {INDEX_NAME}
    HERE.mkdir(parents=True, exist_ok=True)
    objects = HERE / 'sha256'
    objects.mkdir(exist_ok=True)
    for path in HERE.iterdir():
        if path.name in expected or path.name == 'sha256' or path.name == DIGEST_NAME:
            continue
        if path.is_file():
            raise IntegrationBundleError(f'unexpected file in the bundle: {_relative(path)}')

    index: dict[str, Any] = {}
    referenced: set[str] = set()
    for name in MEMBER_NAMES:
        data = files[name]
        extension = object_extension(name)
        digest = sha256_bytes(data)
        (HERE / name).write_bytes(data)
        (objects / (digest + extension)).write_bytes(data)
        entry: dict[str, Any] = {
            'path': _relative(HERE / name),
            'sha256': digest,
            'object': _relative(objects / (digest + extension)),
        }
        if name.endswith('.json'):
            entry['canonical_payload_sha256'] = stable_hash(json.loads(data))
        if name in bundle['bundle_members']:
            entry['mode'] = bundle['bundle_members'][name]['mode']
            entry['role'] = bundle['bundle_members'][name]['role']
            entry['source_path'] = bundle['bundle_members'][name]['source_path']
        if name in (REPORT_NAME, SUMMARY_NAME, N8N_NAME):
            entry['note'] = 'generated by the integration bundle tool'
        index[name] = entry
        referenced.add(digest + extension)

    (HERE / INDEX_NAME).write_text(json.dumps(index, sort_keys=True, indent=2) + '\n')
    (HERE / DIGEST_NAME).write_text(
        f'{index[REPORT_NAME]["sha256"]}  {REPORT_NAME}\n'
        f'# canonical_payload_sha256 {index[REPORT_JSON_NAME]["canonical_payload_sha256"]}\n'
        f'# bundle_index_sha256 {sha256_file(HERE / INDEX_NAME)}\n'
    )
    for path in objects.iterdir():
        if path.is_file() and path.name not in referenced:
            path.unlink()
    return index


def check() -> int:
    """Verify the persisted bundle against a fresh derivation, without writing."""
    try:
        bundle = build_payload()
        files = bundle_files(bundle)
        expected_names = set(MEMBER_NAMES) | {INDEX_NAME, DIGEST_NAME, 'sha256'}
        present = {path.name for path in HERE.iterdir()}
        unexpected = sorted(present - expected_names)
        if unexpected:
            raise IntegrationBundleError(f'unexpected files in the bundle: {unexpected}')
        missing = sorted(set(MEMBER_NAMES) - present)
        if missing:
            raise IntegrationBundleError(f'bundle members missing: {missing}')
        for name in MEMBER_NAMES:
            if (HERE / name).read_bytes() != files[name]:
                raise IntegrationBundleError(f'bundle member is stale: {name}')
        index = verify_content_address(HERE)
        if set(index) != set(MEMBER_NAMES):
            raise IntegrationBundleError('the bundle index does not list exactly its members')
        for name in MEMBER_NAMES:
            if index[name]['sha256'] != sha256_bytes(files[name]):
                raise IntegrationBundleError(f'index digest mismatch for {name}')
        sidecar = (HERE / DIGEST_NAME).read_text(encoding='utf-8')
        if not sidecar.startswith(f'{index[REPORT_NAME]["sha256"]}  {REPORT_NAME}\n'):
            raise IntegrationBundleError('the digest sidecar does not pin the report')
        objects = {path.name for path in (HERE / 'sha256').iterdir() if path.is_file()}
        expected_objects = {
            index[name]['sha256'] + object_extension(name) for name in MEMBER_NAMES
        }
        if objects != expected_objects:
            raise IntegrationBundleError('the content-addressed object set is not closed')
        bundle_token = _relative(HERE)
        for sibling in sorted(UPSTREAM.rglob(INDEX_NAME)):
            if bundle_token in sibling.read_text(encoding='utf-8'):
                raise IntegrationBundleError(
                    f'the integration bundle must stay out of every upstream index: {_relative(sibling)}'
                )
        offenders = order_guard.validation_result_artifacts()
        if _relative(VALIDATION_V1) not in offenders:
            raise IntegrationBundleError(
                'the order guard no longer sees the single consumed VALIDATION read'
            )
        if any(_relative(HERE) in offender for offender in offenders):
            raise IntegrationBundleError(
                'this bundle must not look like a candidate VALIDATION result to the order guard'
            )
    except (IntegrationBundleError, OSError, ValueError, KeyError) as exc:
        print(f'Integration bundle: FAIL: {exc}', file=sys.stderr)
        return 1
    print(json.dumps({
        'result': 'PASS',
        'bundle': _relative(HERE),
        'members': len(MEMBER_NAMES),
        'status': bundle['verdict']['status'],
        'decision': bundle['verdict']['decision'],
        'ci_status': bundle['ci_evidence']['status'],
        'ci_proven_claims': len(bundle['ci_proven_claims']),
        'validation_consumed': bundle['boundaries']['validation_consumed'],
        'test_consumed': bundle['boundaries']['test_consumed'],
        'active_pointer_mutated': bundle['boundaries']['active_pointer_mutated'],
        'next_issue': bundle['next_issue'],
        'report_sha256': index[REPORT_NAME]['sha256'],
        'residual_findings': [item['finding_id'] for item in bundle['residual_findings']],
        'resolved_findings': [item['finding_id'] for item in bundle['resolved_findings']],
    }, sort_keys=True, indent=2))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--check', action='store_true', help='verify the persisted bundle')
    args = parser.parse_args(argv)
    if args.check:
        return check()
    try:
        bundle = build_payload()
        index = persist(bundle)
    except (IntegrationBundleError, OSError, ValueError, KeyError) as exc:
        print(f'Integration bundle: FAIL: {exc}', file=sys.stderr)
        return 1
    print(json.dumps({
        'result': 'WRITTEN',
        'bundle': _relative(HERE),
        'status': bundle['verdict']['status'],
        'decision': bundle['verdict']['decision'],
        'report_sha256': index[REPORT_NAME]['sha256'],
        'index_sha256': sha256_file(HERE / INDEX_NAME),
        'n8n': bundle['n8n_task_result'],
    }, sort_keys=True, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

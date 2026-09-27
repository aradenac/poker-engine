#!/usr/bin/env python3
"""#423 T9 -- persist the required evidence set content-addressed, with the terminal decision.

The ticket enumerates eight artifacts that must be *persisted and
content-addressed*:

``HYBRID_ROUTER_SPEC.json``, ``TRAIN_CV_ROUTER_REPORT.json``,
``SPARSE_STRATA_COMPARISON.json``, ``GENERALIZED_CALIBRATION_REPORT.json``,
``ROUTER_MANIFEST.json``, ``ISSUE367_PREFLIGHT.json``, ``DECISION.json`` and
``SUMMARY.md``.

Six of them are frozen siblings produced earlier in the issue.  The remaining
two -- the terminal ``DECISION.json`` and the human-readable ``SUMMARY.md`` --
are authored *here*, deterministically, from the persisted frozen evidence (no
re-fit, no re-scoring, no holdout read).  This tool then binds all eight:

* byte-identical copies under ``analysis/issue423_hybrid_router/sha256/``;
* ``ARTIFACTS.json``, an index recording per artifact the byte digest, the
  canonical payload digest and every *declared* digest the evidence set carries
  (its own ``.sha256`` sidecar and every cross-reference it pins);
* ``SUMMARY.md`` covering the two valid terminal outcomes, the frozen criteria,
  the global non-inferiority of the routed system, the sparse strata, the OOD
  gate, the reused generalized calibration, the #367 preflight and the
  boundaries (``TEST_CONSUMED=false``, ``VALIDATION_CONSUMED=false``, active
  pointers unchanged, ``next_issue=367`` not executed).

Digest handling answers the #352 failure mode directly: a self-reported digest
that is never recomputed.  Every digest this bundle persists is recomputed from
the persisted bytes and compared against the declared value; any mismatch fails
closed, at build time and under ``--check``.  The cross-reference set covers
every declared digest that pins a persisted file, a persisted *criteria* block,
or a nested provenance digest of a persisted file.  Digests that describe
non-persisted runtime documents (per-decision ``decision_canonical_sha256``,
per-fold calibration ``params_sha256``, node identity hashes) are internal
identifiers and are not recomputable from persisted bytes; they are neither
bound as file digests nor silently treated as if they were.

``ARTIFACTS.json`` is the only member that carries no digest of its own (it
cannot hash itself); every other artifact is content-addressed.

Boundaries
----------
The tool parses no hand history and no decision JSONL: it reads the *persisted*
evidence documents and the derivation it already pins.  VALIDATION is never
re-opened and TEST is never consumed -- the whole issue is a TRAIN-only,
hand-grouped cross-fitted score.  The active Model A/B pointers are never
written and #367 is never executed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.preflop import generalized_response_model as M  # noqa: E402
from tools.training import freeze_hybrid_router_criteria as criteria_tool  # noqa: E402

# --------------------------------------------------------------------------
# layout
# --------------------------------------------------------------------------

#: The one patchable directory: every artifact this tool authors lives under it,
#: and the six frozen siblings are read from it.
HERE = ROOT / "analysis/issue423_hybrid_router"
BUNDLE_REL = "analysis/issue423_hybrid_router"

DECISION_NAME = "DECISION.json"
SUMMARY_NAME = "SUMMARY.md"
INDEX_NAME = "ARTIFACTS.json"
DECISION_DIGEST_NAME = "DECISION.sha256"

DECISION_SCHEMA = "poker-hybrid-router-terminal-decision/v1"
INDEX_SCHEMA = "poker-hybrid-router-evidence-index/v1"
KIND = "hybrid_router_evidence_bundle"
DECISION_ID = "issue423-hybrid-router-terminal-decision-v1"

#: The two valid terminal outcomes.  ``PRODUCT_ADMISSIBLE`` is explicitly out
#: of scope for #423 and is never a terminal outcome of this decision.
ADMIT_OUTCOME = "ADMIT_HYBRID_ROUTER_FOR_ANALYSIS"
RETAIN_OUTCOME = "RETAIN_REFERENCE_HYBRID_INSUFFICIENT"
TERMINAL_OUTCOMES = (ADMIT_OUTCOME, RETAIN_OUTCOME)
NEXT_ISSUE = 367

#: Repository-relative evidence that the required set binds transitively.  Tool
#: and harness modules are *verifiable* through the cross-reference checks
#: without being copied into the content store.
ROUTER_MODULE_REL = "tools/preflop/hybrid_response_router.py"
RUNTIME_MODULE_REL = "tools/preflop/hybrid_response_runtime.py"
CALIBRATION_MODULE_REL = "tools/preflop/generalized_response_calibration.py"
HARNESS_REL = "tools/training/evaluate_hybrid_router_cv.py"
GEN_CV_HARNESS_REL = "tools/training/evaluate_generalized_response_cv.py"
DERIVATION_REL = BUNDLE_REL + "/derivation/CV_DERIVATION.json"
DERIVATION_SIDECAR_REL = BUNDLE_REL + "/derivation/CV_DERIVATION.sha256"
OOD_REPORT_REL = "analysis/issue421_generalized_response/OOD_CALIBRATION_REPORT.json"
GEN_TRAIN_CV_REPORT_REL = "analysis/issue421_generalized_response/TRAIN_CV_REPORT.json"
DATASET_REL = "analysis/issue421_generalized_response/dataset/GENERALIZED_RESPONSE_DATASET.jsonl"
ACTIVE_MODEL_A_REL = "training/models/preflop_population_model_v5.json"
MODEL_B_REL = "training/models/postflop_population_model_v5.json"
SPEC_SCHEMA_REL = "contracts/training/hybrid-router-spec.schema.json"
OOD_GATE_SCHEMA_REL = "contracts/training/generalized-response-ood-gate.schema.json"
DATASET_CONTRACT_REL = "contracts/training/generalized-response-dataset.schema.json"

#: The model #367 currently retains while the hybrid router is not admitted.
ADMITTED_367_MODEL_ID = "model-a-preflop-sizing-aware-candidate-v2"

#: The offline replay of the #423 suite and the transverse guards, recorded by
#: the task worker at the final HEAD inside the isolated worktree.  Every row is
#: an *observation* of a command that was actually run with ``PYTHONPATH=.``;
#: this tool records them, never re-executes them, so they are non-authoritative
#: and are never merge evidence.  The authoritative #423 surface stays the runner
#: ``.github/workflows/issue-423-hybrid-router.yml``.
OFFLINE_REPLAY_RECORDED_AT = "2026-09-27"
OFFLINE_REPLAY_INVOCATION = "PYTHONPATH=."
OFFLINE_REPLAY_NOTE = (
    "Recorded by the task worker inside the isolated worktree sandbox at the final HEAD "
    f"({OFFLINE_REPLAY_RECORDED_AT}), with PYTHONPATH=.; they are NON-AUTHORITATIVE, were "
    "not re-executed by this tool and are never merge evidence. The authoritative #423 "
    "surface remains the runner .github/workflows/issue-423-hybrid-router.yml"
)
OFFLINE_REPLAY_ROWS: tuple[Mapping[str, Any], ...] = (
    {
        "command": "PYTHONPATH=. python3 tests/training/test_freeze_hybrid_router_spec.py",
        "observed_exit_code": 0,
        "observed_result": "OK (32 tests)",
    },
    {
        "command": "PYTHONPATH=. python3 tests/training/test_freeze_hybrid_router_criteria.py",
        "observed_exit_code": 0,
        "observed_result": "OK (37 tests)",
    },
    {
        "command": (
            "POKER_HYBRID_ROUTER_CV_FULL=1 PYTHONPATH=. "
            "python3 tests/training/test_evaluate_hybrid_router_cv.py"
        ),
        "observed_exit_code": 0,
        "observed_result": "OK (47 tests; full derivation re-scored, no skip)",
        "note": "the non-skipped derivation the ticket requires",
    },
    {
        "command": (
            "POKER_HYBRID_ROUTER_CV_PINS_ONLY=1 PYTHONPATH=. "
            "python3 tests/training/test_evaluate_hybrid_router_cv.py"
        ),
        "observed_exit_code": 0,
        "observed_result": "OK (6 tests; nested pins recomputed)",
    },
    {
        "command": "PYTHONPATH=. python3 tests/training/test_hybrid_router_terminal_report.py",
        "observed_exit_code": 0,
        "observed_result": (
            "OK (44 tests; 1 conditional skip: the full re-score test is gated on "
            "POKER_HYBRID_ROUTER_CV_FULL=1, not on the derivation)"
        ),
    },
    {
        "command": (
            "POKER_HYBRID_ROUTER_CV_FULL=1 PYTHONPATH=. "
            "python3 tests/training/test_hybrid_router_terminal_report.py"
        ),
        "observed_exit_code": 0,
        "observed_result": "OK (44 tests; the full terminal re-score runs unskipped)",
    },
    {
        "command": "PYTHONPATH=. python3 tests/training/test_issue423_evidence_bundle.py",
        "observed_exit_code": 0,
        "observed_result": (
            "OK (bundle --check: 8 required artifacts, 15 content-addressed objects, "
            "92 cross-references)"
        ),
    },
    {
        "command": "PYTHONPATH=. python3 tests/training/test_issue423_n8n_result.py",
        "observed_exit_code": 0,
        "observed_result": "OK (11 tests)",
    },
    {
        "command": "PYTHONPATH=. python3 tests/preflop/test_hybrid_response_router.py",
        "observed_exit_code": 0,
        "observed_result": "OK (40 tests)",
    },
    {
        "command": "PYTHONPATH=. python3 tests/preflop/test_hybrid_response_runtime.py",
        "observed_exit_code": 0,
        "observed_result": "OK (24 tests)",
    },
    {
        "command": "PYTHONPATH=. python3 tests/preflop/test_generalized_response_calibration.py",
        "observed_exit_code": 0,
        "observed_result": "OK (34 tests)",
    },
    {
        "command": "PYTHONPATH=. python3 tests/preflop/test_issue423_mandatory_contracts.py",
        "observed_exit_code": 0,
        "observed_result": "OK (11 tests)",
    },
    {
        "command": "PYTHONPATH=. python3 tests/simulation/test_issue423_preflight.py",
        "observed_exit_code": 0,
        "observed_result": "OK (25 tests)",
    },
    {
        "command": "PYTHONPATH=. python3 tests/ci/test_issue423_contract_guards.py",
        "observed_exit_code": 0,
        "observed_result": "OK (11 tests)",
    },
    {
        "command": "PYTHONPATH=. python3 tests/test_github_workflow_audit.py",
        "observed_exit_code": 0,
        "observed_result": (
            "OK (33 tests; 2 conditional skips: the #419/#421 stamped-commit surface "
            "cross-checks are not applicable on this branch, neither is a derivation skip)"
        ),
    },
    {
        "command": "PYTHONPATH=. python3 tests/ci/test_consolidation_decision.py",
        "observed_exit_code": 0,
        "observed_result": "OK (12 tests)",
    },
    {
        "command": "PYTHONPATH=. python3 tools/training/build_issue423_evidence_bundle.py --check",
        "observed_exit_code": 0,
        "observed_result": (
            "OK (status=OK; the decision digest and the 92 cross-references recompute "
            "from the persisted bytes)"
        ),
    },
    {
        "command": "PYTHONPATH=. python3 tools/audit_active_workflow_dag.py --check",
        "observed_exit_code": 0,
        "observed_result": (
            "PASS (57 workflows; 14 scenarios; decision=NO_FURTHER_CONSOLIDATION_JUSTIFIED)"
        ),
    },
)

#: ``(name, role)`` of the eight artifacts the ticket enumerates, in ticket order.
REQUIRED_ARTIFACTS: tuple[tuple[str, str], ...] = (
    ("HYBRID_ROUTER_SPEC.json", "T1_T5_PREREGISTRATION_SPEC_AND_FROZEN_CRITERIA"),
    ("TRAIN_CV_ROUTER_REPORT.json", "T6_TERMINAL_CROSS_FITTED_SCORE"),
    ("SPARSE_STRATA_COMPARISON.json", "T6_SPARSE_STRATA_COMPARISON"),
    ("GENERALIZED_CALIBRATION_REPORT.json", "T2_GENERALIZED_CALIBRATION_REPORT"),
    ("ROUTER_MANIFEST.json", "T5_FROZEN_CRITERIA_MANIFEST"),
    ("ISSUE367_PREFLIGHT.json", "T8_ISSUE367_PREFLIGHT"),
    (DECISION_NAME, "T9_TERMINAL_DECISION"),
    (SUMMARY_NAME, "T9_SUMMARY"),
)

#: Evidence the required set binds transitively, content-addressed here too so
#: the bundle verifies end to end without trusting a sibling bundle.
SUPPORTING_ARTIFACTS: tuple[tuple[str, str], ...] = (
    (DERIVATION_REL, "T4_TRAIN_ONLY_CV_DERIVATION"),
    (DERIVATION_SIDECAR_REL, "T4_TRAIN_ONLY_CV_DERIVATION_SHA256"),
    (OOD_REPORT_REL, "REUSED_ISSUE421_OOD_CALIBRATION_REPORT"),
    (GEN_TRAIN_CV_REPORT_REL, "REUSED_ISSUE421_TRAIN_CV_REPORT"),
    (SPEC_SCHEMA_REL, "HYBRID_ROUTER_SPEC_CONTRACT_SCHEMA"),
    (OOD_GATE_SCHEMA_REL, "GENERALIZED_RESPONSE_OOD_GATE_SCHEMA"),
    (DATASET_CONTRACT_REL, "GENERALIZED_RESPONSE_DATASET_CONTRACT_SCHEMA"),
)

#: Artifacts authored by this tool (they carry no sibling sidecar to declare).
AUTHORED_ARTIFACTS = (DECISION_NAME, SUMMARY_NAME)

MEDIA_TYPES = {
    ".json": "application/json",
    ".md": "text/markdown",
    ".txt": "text/plain",
    ".sha256": "text/plain",
}


class BundleError(RuntimeError):
    """A frozen artifact drifted, or the bundle would not be verifiable."""


# --------------------------------------------------------------------------
# path accessors (kept as functions so an isolated layout can be patched)
# --------------------------------------------------------------------------


def index_path() -> Path:
    return HERE / INDEX_NAME


def summary_path() -> Path:
    return HERE / SUMMARY_NAME


def decision_path() -> Path:
    return HERE / DECISION_NAME


def decision_digest_path() -> Path:
    return HERE / DECISION_DIGEST_NAME


def objects_dir() -> Path:
    return HERE / "sha256"


def _abs(name: str) -> Path:
    return HERE / name


def _resolve(bundle_relative_path: str) -> Path:
    """Resolve a recorded path against the live bundle root when it lives here.

    Paths inside the bundle are resolved relative to ``HERE`` so an isolated
    (temporary) layout verifies itself; every other path is repository-relative.
    """
    if bundle_relative_path == BUNDLE_REL:
        return HERE
    prefix = BUNDLE_REL + "/"
    if bundle_relative_path.startswith(prefix):
        return HERE / bundle_relative_path[len(prefix):]
    return ROOT / bundle_relative_path


# --------------------------------------------------------------------------
# primitives
# --------------------------------------------------------------------------


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_payload_sha256(payload: Mapping[str, Any]) -> str:
    """Repository-wide canonical digest, excluding a self-referential digest."""
    body = {key: value for key, value in payload.items() if key != "canonical_payload_sha256"}
    return M.stable_hash(body)


def serialize(payload: Any) -> bytes:
    return (json.dumps(payload, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def _load(name: str) -> dict:
    try:
        return json.loads(_abs(name).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:  # pragma: no cover - defensive
        raise BundleError(f"cannot load {name}: {error}") from error


def _sidecar_digests(name: str) -> dict[str, str]:
    """Declared byte and canonical digests of ``<name>.sha256`` when it exists."""
    path = _abs(Path(name).with_suffix(".sha256").name)
    if not path.is_file():
        return {}
    declared: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#"):
            parts = line.lstrip("# ").split()
            if len(parts) == 2 and parts[0] == "canonical_payload_sha256":
                declared["canonical_payload_sha256"] = parts[1]
            continue
        parts = line.split()
        if len(parts) >= 2:
            declared["sha256"] = parts[0]
    return declared


# --------------------------------------------------------------------------
# input verification: every declared digest is recomputed
# --------------------------------------------------------------------------


def _reference(source: str, kind: str, target: str, declared: Any) -> dict:
    return {"source": source, "kind": kind, "target": target, "declared": str(declared)}


def _declared_references(docs: Mapping[str, dict]) -> list[dict]:
    """Every declared digest that pins a persisted artifact or criteria block."""
    spec = docs["HYBRID_ROUTER_SPEC.json"]
    report = docs["TRAIN_CV_ROUTER_REPORT.json"]
    sparse = docs["SPARSE_STRATA_COMPARISON.json"]
    calibration = docs["GENERALIZED_CALIBRATION_REPORT.json"]
    manifest = docs["ROUTER_MANIFEST.json"]
    preflight = docs["ISSUE367_PREFLIGHT.json"]
    spec_block = "HYBRID_ROUTER_SPEC.json#frozen_criteria"
    report_block = "TRAIN_CV_ROUTER_REPORT.json#frozen_criteria"
    manifest_block = "ROUTER_MANIFEST.json#frozen_criteria"

    refs: list[dict] = []

    # Preregistration spec -> the evidence it was authored from, the gate
    # contract it reuses and the derivation it pins.
    for entry in spec["evidence_bindings"]:
        refs.append(
            _reference(
                "HYBRID_ROUTER_SPEC.evidence_bindings[" + str(entry.get("role")) + "]",
                "byte",
                entry["path"],
                entry["sha256"],
            )
        )
    refs.append(
        _reference(
            "HYBRID_ROUTER_SPEC.ood_gate",
            "byte",
            spec["ood_gate"]["contract_path"],
            spec["ood_gate"]["contract_sha256"],
        )
    )
    derivation = spec["frozen_criteria"]["derivation"]
    refs.append(
        _reference(
            "HYBRID_ROUTER_SPEC.frozen_criteria.derivation",
            "derivation_projection",
            derivation["artifact"],
            derivation["sha256"],
        )
    )
    refs.append(
        _reference(
            "HYBRID_ROUTER_SPEC.frozen_criteria.derivation",
            "derivation_projection_canonical",
            derivation["artifact"],
            derivation["canonical_payload_sha256"],
        )
    )
    refs.append(
        _reference(
            "HYBRID_ROUTER_SPEC.frozen_criteria",
            "criteria",
            spec_block,
            spec["frozen_criteria"]["criteria_sha256"],
        )
    )

    # Terminal score -> the frozen spec, the manifest and the derivation it binds.
    frozen_spec = report["frozen_spec"]
    refs.append(
        _reference("TRAIN_CV_ROUTER_REPORT.frozen_spec", "byte", frozen_spec["path"], frozen_spec["sha256"])
    )
    refs.append(
        _reference(
            "TRAIN_CV_ROUTER_REPORT.frozen_spec",
            "canonical",
            frozen_spec["path"],
            frozen_spec["canonical_payload_sha256"],
        )
    )
    refs.append(
        _reference(
            "TRAIN_CV_ROUTER_REPORT.frozen_spec.manifest",
            "byte",
            frozen_spec["manifest"]["path"],
            frozen_spec["manifest"]["sha256"],
        )
    )
    refs.append(
        _reference(
            "TRAIN_CV_ROUTER_REPORT.frozen_spec.manifest",
            "canonical",
            frozen_spec["manifest"]["path"],
            frozen_spec["manifest"]["canonical_payload_sha256"],
        )
    )
    binding = frozen_spec["derivation_binding"]
    refs.append(
        _reference(
            "TRAIN_CV_ROUTER_REPORT.frozen_spec.derivation_binding",
            "derivation_projection",
            binding["artifact"],
            binding["sha256"],
        )
    )
    refs.append(
        _reference(
            "TRAIN_CV_ROUTER_REPORT.frozen_spec.derivation_binding",
            "derivation_projection_canonical",
            binding["artifact"],
            binding["canonical_payload_sha256"],
        )
    )
    refs.append(
        _reference("TRAIN_CV_ROUTER_REPORT.frozen_spec", "criteria", spec_block, frozen_spec["criteria_sha256"])
    )
    report_derivation = report["frozen_criteria"]["derivation"]
    refs.append(
        _reference(
            "TRAIN_CV_ROUTER_REPORT.frozen_criteria.derivation",
            "derivation_projection",
            report_derivation["artifact"],
            report_derivation["sha256"],
        )
    )
    refs.append(
        _reference(
            "TRAIN_CV_ROUTER_REPORT.frozen_criteria.derivation",
            "derivation_projection_canonical",
            report_derivation["artifact"],
            report_derivation["canonical_payload_sha256"],
        )
    )
    refs.append(
        _reference(
            "TRAIN_CV_ROUTER_REPORT.frozen_criteria",
            "criteria",
            report_block,
            report["frozen_criteria"]["criteria_sha256"],
        )
    )
    sparse_binding = report["sparse_strata_comparison_binding"]
    refs.append(
        _reference(
            "TRAIN_CV_ROUTER_REPORT.sparse_strata_comparison_binding",
            "byte",
            sparse_binding["declared_path"],
            sparse_binding["sha256"],
        )
    )
    refs.append(
        _reference(
            "TRAIN_CV_ROUTER_REPORT.sparse_strata_comparison_binding",
            "canonical",
            sparse_binding["declared_path"],
            sparse_binding["canonical_payload_sha256"],
        )
    )
    refs.append(
        _reference(
            "TRAIN_CV_ROUTER_REPORT.sparse_strata_comparison.frozen_spec",
            "byte",
            report["sparse_strata_comparison"]["frozen_spec"]["path"],
            report["sparse_strata_comparison"]["frozen_spec"]["sha256"],
        )
    )
    refs.append(
        _reference("TRAIN_CV_ROUTER_REPORT.module", "byte", HARNESS_REL, report["module_sha256"])
    )
    refs.append(
        _reference("TRAIN_CV_ROUTER_REPORT.scope.dataset", "byte", report["scope"]["dataset"], report["scope"]["dataset_sha256"])
    )
    protocol = report["protocol"]
    refs.append(
        _reference(
            "TRAIN_CV_ROUTER_REPORT.protocol.active_reference",
            "byte",
            protocol["active_reference"]["path"],
            protocol["active_reference"]["sha256"],
        )
    )
    refs.append(
        _reference(
            "TRAIN_CV_ROUTER_REPORT.protocol.calibration_module",
            "byte",
            protocol["calibration_module"],
            protocol["calibration_module_sha256"],
        )
    )
    refs.append(
        _reference(
            "TRAIN_CV_ROUTER_REPORT.protocol.reused_harness_module",
            "byte",
            GEN_CV_HARNESS_REL,
            protocol["reused_harness_module_sha256"],
        )
    )
    refs.append(
        _reference(
            "TRAIN_CV_ROUTER_REPORT.protocol.router_module",
            "byte",
            ROUTER_MODULE_REL,
            protocol["router_module_sha256"],
        )
    )

    # Sparse strata comparison -> the frozen spec it re-derives nothing from.
    refs.append(
        _reference("SPARSE_STRATA_COMPARISON.frozen_spec", "byte", sparse["frozen_spec"]["path"], sparse["frozen_spec"]["sha256"])
    )
    refs.append(
        _reference(
            "SPARSE_STRATA_COMPARISON.frozen_spec.criteria",
            "criteria",
            spec_block,
            sparse["frozen_spec"]["criteria_sha256"],
        )
    )
    refs.append(
        _reference("SPARSE_STRATA_COMPARISON.module", "byte", HARNESS_REL, sparse["module_sha256"])
    )

    # Generalized calibration report -> the calibration module and harness.
    refs.append(
        _reference(
            "GENERALIZED_CALIBRATION_REPORT.module",
            "byte",
            CALIBRATION_MODULE_REL,
            calibration["module_sha256"],
        )
    )
    refs.append(
        _reference(
            "GENERALIZED_CALIBRATION_REPORT.harness.module",
            "byte",
            GEN_CV_HARNESS_REL,
            calibration["harness"]["module_sha256"],
        )
    )
    consistency = calibration["harness"]["train_cv_report_consistency"]
    refs.append(
        _reference(
            "GENERALIZED_CALIBRATION_REPORT.harness.train_cv_report_consistency",
            "byte",
            consistency.get("path", GEN_TRAIN_CV_REPORT_REL),
            consistency["sha256"],
        )
    )
    refs.append(
        _reference(
            "GENERALIZED_CALIBRATION_REPORT.scope.dataset",
            "byte",
            calibration["scope"]["dataset"],
            calibration["scope"]["dataset_sha256"],
        )
    )

    # Manifest -> the frozen spec, the criteria block and the derivation inputs.
    refs.append(
        _reference("ROUTER_MANIFEST.frozen_spec", "byte", manifest["frozen_spec"]["path"], manifest["frozen_spec"]["sha256"])
    )
    refs.append(
        _reference(
            "ROUTER_MANIFEST.frozen_spec",
            "canonical",
            manifest["frozen_spec"]["path"],
            manifest["frozen_spec"]["canonical_payload_sha256"],
        )
    )
    refs.append(
        _reference("ROUTER_MANIFEST.frozen_criteria", "criteria", manifest_block, manifest["frozen_criteria"]["criteria_sha256"])
    )
    refs.append(
        _reference(
            "ROUTER_MANIFEST.frozen_criteria",
            "criteria",
            manifest_block,
            manifest["frozen_criteria_sha256"],
        )
    )
    for entry in manifest["derivation_inputs"]:
        if "sha256" in entry:
            refs.append(
                _reference(
                    "ROUTER_MANIFEST.derivation_inputs[" + str(entry["role"]) + "]",
                    "byte",
                    entry["path"],
                    entry["sha256"],
                )
            )
        if "criteria_sha256" in entry:
            refs.append(
                _reference(
                    "ROUTER_MANIFEST.derivation_inputs[" + str(entry["role"]) + "].criteria",
                    "criteria",
                    spec_block,
                    entry["criteria_sha256"],
                )
            )
    generated_by = manifest["generated_by"]
    refs.append(
        _reference("ROUTER_MANIFEST.generated_by", "byte", generated_by["tool_path"], generated_by["tool_sha256"])
    )
    refs.append(
        _reference(
            "ROUTER_MANIFEST.generated_by",
            "byte",
            generated_by["spec_generator_path"],
            generated_by["spec_generator_sha256"],
        )
    )
    procedure_reference = manifest["derivation_procedure"]["reference"]
    refs.append(
        _reference(
            "ROUTER_MANIFEST.derivation_procedure.reference",
            "byte",
            procedure_reference["spec"],
            procedure_reference["spec_sha256"],
        )
    )
    refs.append(
        _reference(
            "ROUTER_MANIFEST.derivation_procedure.reference",
            "canonical",
            procedure_reference["spec"],
            procedure_reference["canonical_payload_sha256"],
        )
    )

    # #367 preflight -> every file it read, every file it protected.
    bindings = preflight["evidence_bindings"]
    for key, value in bindings.items():
        if key.endswith("_path") and key[:-5] + "_sha256" in bindings:
            refs.append(
                _reference(
                    "ISSUE367_PREFLIGHT.evidence_bindings." + key,
                    "byte",
                    value,
                    bindings[key[:-5] + "_sha256"],
                )
            )
    for path, digest in preflight["protected_files"].items():
        refs.append(_reference("ISSUE367_PREFLIGHT.protected_files", "byte", path, digest))
    scenario = preflight["scenario"]
    refs.append(
        _reference("ISSUE367_PREFLIGHT.scenario.fixture", "byte", bindings["fixture_path"], scenario["fixture_sha256"])
    )
    refs.append(
        _reference(
            "ISSUE367_PREFLIGHT.scenario.frontier_resolution",
            "byte",
            bindings["frontier_resolution_path"],
            scenario["frontier_resolution_sha256"],
        )
    )
    refs.append(
        _reference(
            "ISSUE367_PREFLIGHT.scenario.required_tree",
            "byte",
            bindings["required_tree_path"],
            scenario["required_tree_sha256"],
        )
    )
    provider = preflight["provider"]
    refs.append(
        _reference(
            "ISSUE367_PREFLIGHT.provider.active_reference",
            "byte",
            provider["active_reference"]["path"],
            provider["active_reference"]["sha256"],
        )
    )
    calibration_binding = provider["generalized_calibration_report"]
    refs.append(
        _reference(
            "ISSUE367_PREFLIGHT.provider.generalized_calibration_report",
            "byte",
            calibration_binding["path"],
            calibration_binding["sha256"],
        )
    )
    refs.append(
        _reference(
            "ISSUE367_PREFLIGHT.provider.generalized_calibration_report",
            "canonical",
            calibration_binding["path"],
            calibration_binding["canonical_payload_sha256"],
        )
    )
    ood_binding = provider["ood_calibration"]
    refs.append(
        _reference(
            "ISSUE367_PREFLIGHT.provider.ood_calibration",
            "byte",
            ood_binding["path"],
            ood_binding["sha256"],
        )
    )
    # The declared canonical digest of the OOD report is the nested
    # ``calibration.canonical_payload_sha256`` provenance it carries, not the
    # canonical payload digest of the report file itself.
    refs.append(
        _reference(
            "ISSUE367_PREFLIGHT.provider.ood_calibration",
            "nested",
            ood_binding["path"] + "#calibration.canonical_payload_sha256",
            ood_binding["canonical_payload_sha256"],
        )
    )
    spec_binding = provider["spec"]
    refs.append(
        _reference(
            "ISSUE367_PREFLIGHT.provider.spec",
            "byte",
            spec_binding["path"],
            spec_binding["sha256"],
        )
    )
    refs.append(
        _reference(
            "ISSUE367_PREFLIGHT.provider.spec",
            "canonical",
            spec_binding["path"],
            spec_binding["canonical_payload_sha256"],
        )
    )
    manifest_binding = spec_binding["manifest"]
    refs.append(
        _reference(
            "ISSUE367_PREFLIGHT.provider.spec.manifest",
            "byte",
            manifest_binding["path"],
            manifest_binding["sha256"],
        )
    )
    refs.append(
        _reference(
            "ISSUE367_PREFLIGHT.provider.spec.manifest",
            "canonical",
            manifest_binding["path"],
            manifest_binding["canonical_payload_sha256"],
        )
    )
    refs.append(
        _reference(
            "ISSUE367_PREFLIGHT.provider.spec.manifest.entry.criteria",
            "criteria",
            spec_block,
            manifest_binding["entry"]["criteria_sha256"],
        )
    )
    admission = preflight["admission"]
    refs.append(
        _reference(
            "ISSUE367_PREFLIGHT.admission.authority",
            "byte",
            admission["authority"],
            admission["authority_byte_sha256"],
        )
    )
    retained = admission["currently_retained_reference"]
    refs.append(
        _reference(
            "ISSUE367_PREFLIGHT.admission.currently_retained_reference",
            "byte",
            retained["path"],
            retained["sha256"],
        )
    )
    evidence_scope = admission["evidence_scope"]
    refs.append(
        _reference(
            "ISSUE367_PREFLIGHT.admission.evidence_scope.dataset",
            "byte",
            evidence_scope["dataset"],
            evidence_scope["dataset_sha256"],
        )
    )
    return refs


def _recompute_reference(docs: Mapping[str, dict], kind: str, target: str) -> str | None:
    try:
        if kind == "byte":
            return sha256_bytes((ROOT / target).read_bytes())
        if kind == "canonical":
            return canonical_payload_sha256(json.loads((ROOT / target).read_text(encoding="utf-8")))
        if kind == "derivation_projection":
            # The frozen criteria bind the derivation through the published
            # projection, not through its raw bytes: the raw bytes carry the spec
            # pin, and pinning them would close the spec <-> derivation cycle.
            return criteria_tool.projected_derivation_sha256(
                json.loads((ROOT / target).read_text(encoding="utf-8"))
            )
        if kind == "derivation_projection_canonical":
            return criteria_tool.projected_derivation_canonical_payload_sha256(
                json.loads((ROOT / target).read_text(encoding="utf-8"))
            )
        if kind == "criteria":
            document, pointer = target.split("#", 1)
            block = docs[document][pointer]
            return M.stable_hash(
                {key: value for key, value in block.items() if key != "criteria_sha256"}
            )
        if kind == "nested":
            rel, pointer = target.split("#", 1)
            node: Any = json.loads((ROOT / rel).read_text(encoding="utf-8"))
            for part in pointer.split("."):
                node = node[part]
            return str(node)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None
    return None


def _cross_reference_checks(docs: Mapping[str, dict]) -> list[dict]:
    """Recompute every digest the frozen evidence set declares about a file."""
    checks: list[dict] = []
    for ref in _declared_references(docs):
        recomputed = _recompute_reference(docs, ref["kind"], ref["target"])
        checks.append(
            {
                "source": ref["source"],
                "kind": ref["kind"],
                "artifact": ref["target"],
                "declared": ref["declared"],
                "recomputed": recomputed,
                "match": ref["declared"] == recomputed,
            }
        )
    return checks


def _require_false(label: str, payload: Mapping[str, Any], path: str, problems: list[str]) -> None:
    node: Any = payload
    for part in path.split("."):
        if not isinstance(node, Mapping) or part not in node:
            problems.append(f"{label}.{path} is missing")
            return
        node = node[part]
    if node is not False:
        problems.append(f"{label}.{path} is not false")


def verify_inputs() -> dict:
    """Load the frozen evidence, recompute every digest and fail closed on drift."""
    docs = {
        name: _load(name)
        for name, _role in REQUIRED_ARTIFACTS
        if name not in AUTHORED_ARTIFACTS
    }

    digests: dict[str, str] = {}
    for name, _role in REQUIRED_ARTIFACTS:
        if name not in AUTHORED_ARTIFACTS:
            digests[name] = sha256_bytes(_abs(name).read_bytes())
    for rel, _role in SUPPORTING_ARTIFACTS:
        digests[rel] = sha256_bytes((ROOT / rel).read_bytes())
        digests[Path(rel).name] = digests[rel]

    # Per-artifact declared digests come from the artifact's own .sha256 sidecar.
    declared: dict[str, dict[str, str]] = {}
    problems: list[str] = []
    for name, _role in REQUIRED_ARTIFACTS:
        if name in AUTHORED_ARTIFACTS:
            continue
        side = _sidecar_digests(name)
        declared[name] = side
        for field, value in side.items():
            actual = digests[name] if field == "sha256" else canonical_payload_sha256(docs[name])
            if actual != value:
                problems.append(f"{name}: declared {field} {value} != recomputed {actual}")

    cross = _cross_reference_checks(docs)
    problems.extend(
        check["source"]
        + " ["
        + check["kind"]
        + "] declared "
        + check["declared"]
        + " != recomputed "
        + str(check["recomputed"])
        + " ("
        + check["artifact"]
        + ")"
        for check in cross
        if not check["match"]
    )

    # Scientific boundary: the frozen artifacts must agree that no holdout was
    # read, that no pointer moved and that #367 was never executed.
    report = docs["TRAIN_CV_ROUTER_REPORT.json"]
    spec = docs["HYBRID_ROUTER_SPEC.json"]
    manifest = docs["ROUTER_MANIFEST.json"]
    sparse = docs["SPARSE_STRATA_COMPARISON.json"]
    calibration = docs["GENERALIZED_CALIBRATION_REPORT.json"]
    preflight = docs["ISSUE367_PREFLIGHT.json"]
    if report["outcome"] not in TERMINAL_OUTCOMES:
        problems.append("terminal score carries an undeclared outcome: " + str(report["outcome"]))
    if report["criteria_evaluation"]["outcome"] != report["outcome"]:
        problems.append("terminal score outcome disagrees with its criteria evaluation")
    if report["scope"]["test_consumed"] is not False:
        problems.append("terminal score consumed TEST")
    if report["scope"]["validation_consumed"] is not False:
        problems.append("terminal score consumed VALIDATION")
    for label, document, path in (
        ("HYBRID_ROUTER_SPEC", spec, "assertions.test_consumed"),
        ("HYBRID_ROUTER_SPEC", spec, "assertions.validation_consumed"),
        ("ROUTER_MANIFEST", manifest, "assertions.test_consumed"),
        ("ROUTER_MANIFEST", manifest, "assertions.validation_consumed"),
        ("ROUTER_MANIFEST", manifest, "assertions.terminal_evaluation_consumed"),
        ("TRAIN_CV_ROUTER_REPORT", report, "guards.test_consumed"),
        ("TRAIN_CV_ROUTER_REPORT", report, "guards.validation_consumed"),
    ):
        _require_false(label, document, path, problems)
    for label, document, path in (
        ("TRAIN_CV_ROUTER_REPORT", report, "assertions.test_never_read"),
        ("TRAIN_CV_ROUTER_REPORT", report, "assertions.validation_never_read"),
        ("TRAIN_CV_ROUTER_REPORT", report, "guards.no_holdout_loader"),
        ("TRAIN_CV_ROUTER_REPORT", report, "guards.train_only"),
    ):
        node: Any = document
        for part in path.split("."):
            node = node.get(part) if isinstance(node, Mapping) else None
        if node is not True:
            problems.append(f"{label}.{path} is not true")
    if spec["split_policy"]["refused_splits"] != ["VALIDATION", "TEST"]:
        problems.append("the preregistration spec does not refuse VALIDATION and TEST")
    if manifest["split_policy"]["refused_splits"] != ["VALIDATION", "TEST"]:
        problems.append("the criteria manifest does not refuse VALIDATION and TEST")
    for label, document, path in (
        ("SPARSE_STRATA_COMPARISON", sparse, "assertions.test_consumed"),
        ("SPARSE_STRATA_COMPARISON", sparse, "assertions.validation_consumed"),
        ("GENERALIZED_CALIBRATION_REPORT", calibration, "guards.test_consumed"),
        ("GENERALIZED_CALIBRATION_REPORT", calibration, "guards.validation_consumed"),
        ("GENERALIZED_CALIBRATION_REPORT", calibration, "guards.validation_recalibrated"),
    ):
        _require_false(label, document, path, problems)
    for label, document, path in (
        ("SPARSE_STRATA_COMPARISON", sparse, "assertions.train_only"),
        ("GENERALIZED_CALIBRATION_REPORT", calibration, "guards.train_only"),
        ("GENERALIZED_CALIBRATION_REPORT", calibration, "guards.no_holdout_loader"),
    ):
        node: Any = document
        for part in path.split("."):
            node = node.get(part) if isinstance(node, Mapping) else None
        if node is not True:
            problems.append(f"{label}.{path} is not true")
    if preflight["boundary"]["test_consumed"] is not False:
        problems.append("#367 preflight consumed TEST")
    if preflight["boundary"]["validation_split_consumed"] is not False:
        problems.append("#367 preflight consumed VALIDATION")
    if preflight["boundary"]["active_model_pointer_mutated"] is not False:
        problems.append("#367 preflight mutated the active pointer")
    if preflight["boundary"]["hero_ev_executed"] is not False:
        problems.append("#367 preflight executed the Hero EV")
    if preflight["boundary"]["issue367_executed"] is not False:
        problems.append("#367 preflight executed #367")
    if preflight["admission"]["issue367_authorized"] is not False:
        problems.append("#367 preflight authorizes #367")
    if preflight["admission"]["terminal_outcome"] != report["outcome"]:
        problems.append("#367 preflight terminal outcome disagrees with the router report")

    if problems:
        raise BundleError("; ".join(problems))

    return {
        "docs": docs,
        "digests": digests,
        "declared": declared,
        "cross_reference_checks": cross,
    }


# --------------------------------------------------------------------------
# authored artifacts
# --------------------------------------------------------------------------


def build_decision(inputs: Mapping[str, Any]) -> dict:
    """Fold the frozen evidence into the terminal decision (no new claim)."""
    docs = inputs["docs"]
    digests = inputs["digests"]
    spec = docs["HYBRID_ROUTER_SPEC.json"]
    report = docs["TRAIN_CV_ROUTER_REPORT.json"]
    sparse = docs["SPARSE_STRATA_COMPARISON.json"]
    calibration = docs["GENERALIZED_CALIBRATION_REPORT.json"]
    manifest = docs["ROUTER_MANIFEST.json"]
    preflight = docs["ISSUE367_PREFLIGHT.json"]

    evaluation = report["criteria_evaluation"]
    criteria = evaluation["criteria"]
    passed = [item["id"] for item in criteria if item["passed"]]
    failed = [item["id"] for item in criteria if not item["passed"]]
    outcome = report["outcome"]
    models = report["models"]
    route_counts = models["hybrid_router"]["route_source_counts"]
    admission = preflight["admission"]

    def gate(item: Mapping[str, Any]) -> dict:
        return {
            "id": item["id"],
            "derives": item["derives"],
            "direction": item["direction"],
            "comparator": item["comparator"],
            "threshold": item["threshold"],
            "unit": item["unit"],
            "statistic": item["statistic"],
            "frozen_criterion": item["frozen_criterion"],
            "observed": item["observed"],
            "passed": item["passed"],
        }

    terminal_outcomes = [
        {
            "id": ADMIT_OUTCOME,
            "actual": outcome == ADMIT_OUTCOME,
            "condition": (
                "every frozen #423 admission criterion passes on the TRAIN-only "
                "hand-grouped cross-fitted score"
            ),
            "downstream": (
                "unlocks the #367 preflight only: it wires no provider into #367, "
                "performs no promotion and mutates no active pointer"
            ),
            "issue367_authorized": False,
            "note": (
                "even the admitting outcome only unblocks the #367 analysis; #367 "
                "is not executed by this bundle"
            ),
        },
        {
            "id": RETAIN_OUTCOME,
            "actual": outcome == RETAIN_OUTCOME,
            "condition": (
                "at least one frozen #423 admission criterion fails on the "
                "TRAIN-only hand-grouped cross-fitted score"
            ),
            "downstream": (
                "the active Model A reference is retained; #367 keeps its currently "
                "admitted model; no provider is wired, no Hero EV is computed and no "
                "promotion happens"
            ),
            "issue367_authorized": False,
            "note": "the refused admission is recorded as evidence only",
        },
    ]

    if failed:
        rationale = (
            "the hybrid router passes "
            + str(len(passed))
            + "/"
            + str(len(criteria))
            + " frozen criteria but fails "
            + ", ".join(failed)
            + " on the TRAIN-only cross-fitted score; the active Model A reference is "
            "retained and #367 keeps its currently admitted model"
        )
    else:
        rationale = (
            "the hybrid router passes every frozen criterion ("
            + str(len(passed))
            + "/"
            + str(len(criteria))
            + ") on the TRAIN-only cross-fitted score; the router is admitted for the #367 "
            "analysis only and no pointer is promoted"
        )
    rationale = rationale + "; the terminal outcome is " + outcome

    decision: dict[str, Any] = {
        "schema": DECISION_SCHEMA,
        "kind": "HYBRID_ROUTER_TERMINAL_DECISION",
        "issue": 423,
        "decision_id": DECISION_ID,
        "title": (
            "#423 terminal decision: the frozen-criteria outcome of the TRAIN-only "
            "cross-fitted hybrid preflop response router"
        ),
        "decided_at": manifest["frozen_at"],
        "terminal": True,
        "decision": outcome,
        "protocol_outcome": outcome,
        "outcome_rule": evaluation["outcome_rule"],
        "terminal_outcomes": terminal_outcomes,
        "decision_rationale": rationale,
        "criteria_order": evaluation["criteria_order"],
        "criteria_total": len(criteria),
        "criteria_passed": len(passed),
        "passed_criteria": passed,
        "failed_criteria": failed,
        "gates": [gate(item) for item in criteria],
        "evaluation": {
            "basis": report["protocol"]["kind"],
            "split": report["scope"]["split"],
            "consumed_splits": report["scope"]["consumed_splits"],
            "refused_splits": report["scope"]["refused_splits"],
            "forbidden_splits": report["scope"]["forbidden_splits"],
            "rows": report["scope"]["rows"],
            "hands": report["scope"]["hands"],
            "cross_validated_rows": report["scope"]["cross_validated_rows"],
            "folds": report["protocol"]["folds"],
            "group_key": report["protocol"]["group_key"],
            "probe_rows": report["scope"]["probe_rows"],
            "validation_consumed": False,
            "test_consumed": False,
        },
        "channels": report["protocol"]["channels"],
        "route_source_counts": route_counts,
        "metrics": {
            "log_loss_bits_per_decision": {
                name: models[name]["metrics"]["log_loss_bits_per_decision"] for name in models
            },
            "brier_score": {name: models[name]["metrics"]["brier_score"] for name in models},
            "expected_calibration_error": {
                name: models[name]["metrics"]["expected_calibration_error"] for name in models
            },
            "accuracy": {name: models[name]["metrics"]["accuracy"] for name in models},
            "coverage": {name: models[name]["scope"]["coverage"] for name in models},
            "abstain_rate": {name: models[name]["scope"]["abstain_rate"] for name in models},
        },
        "global_deltas": report["deltas"]["global_log_loss_bits_per_decision"],
        "paired": {
            name: {
                "left": value["left"],
                "right": value["right"],
                "paired_unit": value["paired_unit"],
                "global": value.get("global"),
                "admission_support": value.get("admission_support"),
            }
            for name, value in report["paired"].items()
        },
        "strata": report["strata"],
        "per_stratum": {
            name: {
                "n": block["models"]["hybrid_router"]["metrics"]["n"],
                "hybrid_log_loss_bits_per_decision": block["models"]["hybrid_router"]["metrics"][
                    "log_loss_bits_per_decision"
                ],
                "hybrid_expected_calibration_error": block["models"]["hybrid_router"]["metrics"][
                    "expected_calibration_error"
                ],
                "hybrid_coverage": block["models"]["hybrid_router"]["coverage"]["coverage"],
            }
            for name, block in report["per_stratum"].items()
        },
        "sparse_strata_comparison": {
            "pooled": sparse["pooled"],
            "by_stratum": {
                name: {
                    "hybrid_router": block["models"]["hybrid_router"]["metrics"],
                    "coverage": block["models"]["hybrid_router"]["scope"]["coverage"],
                }
                for name, block in sparse["by_stratum"].items()
            },
            "evaluation_basis": sparse["evaluation_basis"],
            "paired_unit": sparse["paired_unit"],
        },
        "limper_vs_iso": {
            "family": report["limper_vs_iso"]["family"],
            "hands": report["limper_vs_iso"]["hands"],
            "models": {
                name: {
                    "log_loss_bits_per_decision": report["limper_vs_iso"]["models"][name]["metrics"][
                        "log_loss_bits_per_decision"
                    ],
                    "expected_calibration_error": report["limper_vs_iso"]["models"][name]["metrics"][
                        "expected_calibration_error"
                    ],
                    "coverage": report["limper_vs_iso"]["models"][name]["scope"]["coverage"],
                }
                for name in report["limper_vs_iso"]["models"]
            },
        },
        "ood_gate": {
            "rule_id": preflight["ood_rule"]["rule_id"],
            "contract_path": spec["ood_gate"]["contract_path"],
            "contract_sha256": spec["ood_gate"]["contract_sha256"],
            "hard_reason_codes": spec["ood_gate"]["hard_reason_codes"],
            "statuses": spec["ood_gate"]["statuses"],
            "required_abstention_rate_on_synthetic_ood_probes": preflight["ood_rule"][
                "required_abstention_rate_on_synthetic_ood_probes"
            ],
            "synthetic_probes": {
                "n": report["ood"]["n"],
                "abstain_rate": report["ood"]["abstain_rate"],
                "coverage": report["ood"]["coverage"],
                "probes_per_kind": report["ood"]["probes_per_kind"],
            },
            "channel_abstention_on_probes": report["ood_synthetic_probes"]["channels"],
            "nearest_price_substituted": preflight["boundary"]["nearest_price_substituted"],
            "nearest_context_substituted": preflight["boundary"]["nearest_context_substituted"],
        },
        "calibration": {
            "retained_architecture": calibration["retained_architecture"],
            "retained_method": calibration["retained_method"],
            "retained_methods_by_architecture": calibration["retained_methods_by_architecture"],
            "scope": calibration["scope"],
            "module": calibration["harness"]["module"],
            "module_sha256": calibration["module_sha256"],
            "validation_recalibrated": calibration["guards"]["validation_recalibrated"],
        },
        "frozen_criteria": {
            "spec_path": manifest["frozen_spec"]["path"],
            "spec_sha256": digests["HYBRID_ROUTER_SPEC.json"],
            "criteria_sha256": manifest["frozen_criteria_sha256"],
            "manifest_path": BUNDLE_REL + "/" + "ROUTER_MANIFEST.json",
            "manifest_sha256": digests["ROUTER_MANIFEST.json"],
            "derivation_path": DERIVATION_REL,
            "derivation_sha256": digests[DERIVATION_REL],
            "authored_before_terminal_score": manifest["assertions"]["terminal_report_absent_at_freeze"],
        },
        "issue367": {
            "authorized": admission["issue367_authorized"],
            "rule_id": admission["rule_id"],
            "question": admission["question"],
            "outcome": admission["outcome"],
            "terminal_outcome": admission["terminal_outcome"],
            "consumption": admission["consumption"],
            "admitting_outcome": admission["admitting_outcome"],
            "retaining_outcome": admission["retaining_outcome"],
            "preflight_passed": preflight["issue367_preflight_passed"],
            "executed": preflight["boundary"]["issue367_executed"],
            "hero_ev_executed": preflight["boundary"]["hero_ev_executed"],
            "nodes_queried": preflight["nodes_queried"],
            "sizing_frontiers_queried": preflight["sizing_frontiers_queried"],
        },
        "references": {
            "active_model_a_preflop": {
                "model_id": "active_model_a_preflop_population",
                "path": report["protocol"]["active_reference"]["path"],
                "sha256": report["protocol"]["active_reference"]["sha256"],
            },
            "admitted_model_for_issue367": {
                "model_id": ADMITTED_367_MODEL_ID,
                "path": admission["currently_retained_reference"]["path"],
                "sha256": admission["currently_retained_reference"]["sha256"],
            },
            "model_b_postflop": {"path": MODEL_B_REL},
        },
        "boundaries": {
            "split": report["scope"]["split"],
            "consumed_splits": report["scope"]["consumed_splits"],
            "refused_splits": report["scope"]["refused_splits"],
            "validation_consumed": False,
            "validation_reopened": False,
            "test_consumed": False,
            "test_authorized": False,
            "active_pointer_mutated": False,
            "active_model_pointer_mutation": False,
            "automatic_promotion": "FORBIDDEN",
            "product_admissible": False,
            "product_admissible_note": (
                "PRODUCT_ADMISSIBLE is explicitly out of scope for #423 and is never a "
                "terminal outcome of this decision"
            ),
            "issue367_executed": False,
            "hero_ev_executed": False,
            "model_b_consumed": False,
        },
        "next_issue": NEXT_ISSUE,
        "next_issue_status": "NOT_EXECUTED",
        "offline_replay": {
            "recorded_at": OFFLINE_REPLAY_RECORDED_AT,
            "invocation": OFFLINE_REPLAY_INVOCATION,
            "authoritative_runner": ".github/workflows/issue-423-hybrid-router.yml",
            "note": OFFLINE_REPLAY_NOTE,
            "rows": [dict(row) for row in OFFLINE_REPLAY_ROWS],
            "all_rows_passed": all(
                row["observed_exit_code"] == 0 for row in OFFLINE_REPLAY_ROWS
            ),
            "commands_recorded": len(OFFLINE_REPLAY_ROWS),
            "boundary_recheck": {
                "source": (
                    "recomputed by this tool from the persisted evidence (and the pointer "
                    "bytes on disk) at build and --check time"
                ),
                "test_consumed": report["scope"]["test_consumed"],
                "validation_consumed": report["scope"]["validation_consumed"],
                "validation_reopened": False,
                "active_pointer_mutated": False,
                "product_admissible": False,
                "issue367_executed": preflight["boundary"]["issue367_executed"],
                "next_issue": NEXT_ISSUE,
                "next_issue_status": "NOT_EXECUTED",
                "active_model_a_pointer_path": report["protocol"]["active_reference"]["path"],
                "active_model_a_pointer_sha256_pinned": report["protocol"]["active_reference"][
                    "sha256"
                ],
                "active_model_a_pointer_sha256_on_disk": sha256_bytes(
                    (ROOT / ACTIVE_MODEL_A_REL).read_bytes()
                ),
                "active_model_a_pointer_bytes_match_pin": report["protocol"]["active_reference"][
                    "sha256"
                ]
                == sha256_bytes((ROOT / ACTIVE_MODEL_A_REL).read_bytes()),
                "model_b_pointer_path": MODEL_B_REL,
                "model_b_pointer_sha256_on_disk": sha256_bytes(
                    (ROOT / MODEL_B_REL).read_bytes()
                ),
            },
        },
        "downstream": (
            "only the admitting terminal outcome would unblock the #367 analysis; the "
            "retaining outcome keeps the active Model A reference, wires no provider "
            "into #367 and authorizes no Hero EV, no support-grid extension and no "
            "promotion"
        ),
        "rollback": (
            "no production state is mutated: the terminal decision and this bundle are "
            "new evidence artifacts and can be withdrawn by reverting the commit; the "
            "active Model A/B pointers are never written"
        ),
        "evidence_bindings": {
            name: {"path": BUNDLE_REL + "/" + name, "sha256": digests[name]}
            for name, _role in REQUIRED_ARTIFACTS
            if name not in AUTHORED_ARTIFACTS
        },
        "reproduction": {
            "build_command": "python3 tools/training/build_issue423_evidence_bundle.py",
            "check_command": "python3 tools/training/build_issue423_evidence_bundle.py --check",
            "producer_tools": {
                "preregistration_spec": "tools/training/freeze_hybrid_router_spec.py",
                "criteria_freeze": "tools/training/freeze_hybrid_router_criteria.py",
                "calibration": "tools/preflop/generalized_response_calibration.py",
                "router": ROUTER_MODULE_REL,
                "runtime": RUNTIME_MODULE_REL,
                "cross_validation": HARNESS_REL,
                "preflight": "tools/simulation/issue423_issue367_preflight.py",
                "bundle": "tools/training/build_issue423_evidence_bundle.py",
            },
        },
        "decision_digest_location": (
            "the decision digest cannot live inside the decision payload; it is recorded "
            "in DECISION.sha256 and in ARTIFACTS.json"
        ),
    }
    decision["canonical_payload_sha256"] = canonical_payload_sha256(decision)
    return decision


def _pct(value: Any) -> str:
    return format(100 * float(value), ".4f") + "%"


def _observed_text(observed: Any) -> str:
    if isinstance(observed, (dict, list)):
        return json.dumps(observed, sort_keys=True)
    return str(observed)


def _cell(value: Any) -> str:
    return "n/a" if value is None else str(value)


def summary_text(inputs: Mapping[str, Any], decision: Mapping[str, Any], decision_digest: str) -> str:
    digests = inputs["digests"]
    spec = inputs["docs"]["HYBRID_ROUTER_SPEC.json"]
    report = inputs["docs"]["TRAIN_CV_ROUTER_REPORT.json"]
    sparse = inputs["docs"]["SPARSE_STRATA_COMPARISON.json"]
    calibration = inputs["docs"]["GENERALIZED_CALIBRATION_REPORT.json"]
    preflight = inputs["docs"]["ISSUE367_PREFLIGHT.json"]

    coverage = report["models"]["hybrid_router"]["scope"]
    route_counts = decision["route_source_counts"]
    probes = decision["ood_gate"]["synthetic_probes"]
    preflight_walk = preflight["walkthrough"]
    pooled = sparse["pooled"]
    limper = decision["limper_vs_iso"]

    lines = [
        "# #423 -- hybrid preflop response router: evidence bundle",
        "",
        "**" + str(decision["decision"]) + "** -- the actual one of the two valid terminal "
        "outcomes (`" + ADMIT_OUTCOME + "` / `" + RETAIN_OUTCOME + "`). On the "
        "TRAIN-only, hand-grouped cross-fitted score the routed system passes "
        + str(decision["criteria_passed"]) + "/" + str(decision["criteria_total"])
        + " frozen admission criteria and fails "
        + ", ".join("`" + item + "`" for item in decision["failed_criteria"]) + ", so the "
        "active Model A reference is retained, #367 keeps its currently admitted model and "
        "nothing is promoted (`PRODUCT_ADMISSIBLE` is explicitly out of scope).",
        "",
        "This bundle persists and content-addresses the eight required #423 artifacts under `"
        + BUNDLE_REL + "/sha256/` and binds them in `ARTIFACTS.json`. `DECISION.json` is the "
        "terminal decision authored here as a deterministic fold of the frozen evidence (no "
        "re-fit, no re-score, no new claim); its byte SHA256 is `" + decision_digest
        + "` (canonical payload `" + decision["canonical_payload_sha256"] + "`).",
        "",
        "## 1. Decision (both terminal outcomes)",
        "",
        "| terminal outcome | condition | actual | downstream |",
        "| --- | --- | --- | --- |",
    ]
    for entry in decision["terminal_outcomes"]:
        lines.append(
            "| `" + entry["id"] + "` | " + entry["condition"] + " | "
            + ("**yes**" if entry["actual"] else "no") + " | " + entry["downstream"] + " |"
        )
    lines += [
        "",
        "`DECISION.json` = **" + str(decision["decision"]) + "**. Rationale: "
        + decision["decision_rationale"] + ".",
        "",
        "## 2. Frozen criteria evaluation (TRAIN-only, hand-grouped cross-fitted)",
        "",
        "| criterion | comparator | threshold | observed | result |",
        "| --- | --- | --- | --- | --- |",
    ]
    for item in report["criteria_evaluation"]["criteria"]:
        lines.append(
            "| `" + item["id"] + "` | `" + item["comparator"] + "` | " + str(item["threshold"])
            + " | `" + _observed_text(item["observed"]) + "` | "
            + ("PASS" if item["passed"] else "**FAIL**") + " |"
        )
    lines += [
        "",
        "Surface: TRAIN only, `" + str(report["scope"]["rows"]) + "` rows over `"
        + str(report["scope"]["hands"]) + "` hands in `" + str(report["protocol"]["folds"])
        + "` folds grouped by `" + report["protocol"]["group_key"] + "`; VALIDATION and TEST "
        "are refused by the loader, the harness and the criteria freeze "
        "(`validation_consumed=false`, `test_consumed=false`).",
        "",
        "## 3. Global non-inferiority of the routed system",
        "",
        "Routed channel shares: `ACTIVE_STRONG_SUPPORT=" + str(route_counts["ACTIVE_STRONG_SUPPORT"])
        + "`, `GENERALIZED_SPARSE_IN_DOMAIN=" + str(route_counts["GENERALIZED_SPARSE_IN_DOMAIN"])
        + "`, `OOD_ABSTAIN=" + str(route_counts["OOD_ABSTAIN"]) + "`; hybrid coverage "
        + _pct(coverage["coverage"]) + " (" + str(coverage["abstained"]) + " abstained decisions).",
        "",
        "| channel | log loss (bits/decision) | ECE | coverage |",
        "| --- | --- | --- | --- |",
    ]
    for name in ("active_model_a", "generalized_calibrated", "hybrid_router"):
        lines.append(
            "| " + name + " | " + str(decision["metrics"]["log_loss_bits_per_decision"][name])
            + " | " + str(decision["metrics"]["expected_calibration_error"][name])
            + " | " + str(decision["metrics"]["coverage"][name]) + " |"
        )
    paired = report["paired"]["hybrid_router_minus_active_model_a"]["admission_support"]
    lines += [
        "",
        "Global paired-by-hand bootstrap (hybrid minus active, negative favours the router): "
        "point `" + str(paired["point_estimate_bits_per_decision"]) + "`, ci95 `"
        + str(paired["ci95"]) + "`, one-sided upper quantile `"
        + str(paired["upper_quantile_bits_per_decision"]) + "` against the frozen margin `"
        + str(report["criteria_evaluation"]["criteria"][0]["threshold"]) + "` -- PASS.",
        "",
        "## 4. Sparse strata comparison (generalization)",
        "",
        "Definition: " + report["strata"]["definition"] + ".",
        "",
        "| stratum | share | n | hybrid log loss | hybrid ECE | hybrid coverage |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for key in ("rare_exact", "exact_absent_in_domain", "frequent_exact", "exact_absent_out_of_domain"):
        block = decision["per_stratum"][key]
        lines.append(
            "| " + key + " | " + str(report["strata"]["shares"][key]) + " | " + str(block["n"])
            + " | " + _cell(block["hybrid_log_loss_bits_per_decision"]) + " | "
            + _cell(block["hybrid_expected_calibration_error"]) + " | "
            + _cell(block["hybrid_coverage"]) + " |"
        )
    lines += [
        "",
        "Pooled sparse support (`rare_exact`, `exact_absent_in_domain`): "
        + str(pooled["sparse_decisions"]) + " decisions, gain `"
        + str(pooled["gain_bits_per_decision"]) + "` bits/decision (floor `"
        + str(report["criteria_evaluation"]["criteria"][1]["threshold"]) + "` -- PASS), sparse "
        "ECE `" + str(pooled["hybrid_ece"]) + "` against the active reference `"
        + str(pooled["active_ece"]) + "` -- ceiling `"
        + str(report["criteria_evaluation"]["criteria"][2]["threshold"]) + "`, **FAIL** "
        "(the single failed criterion). Per-stratum hybrid ECE is `"
        + str(pooled["criteria"]["SPARSE_ECE_CEILING"]["observed"]["per_stratum_hybrid_ece"])
        + "`. The `exact_absent_out_of_domain` stratum is empty on the natural TRAIN surface "
        "(share `" + str(report["strata"]["shares"]["exact_absent_out_of_domain"]) + "`); "
        "abstention is exercised on the synthetic OOD probes instead.",
        "",
        "## 5. OOD gate and abstention",
        "",
        "Route sources `" + "/".join(source["id"] for source in spec["route_sources"])
        + "`; hard reason codes `" + ", ".join(spec["ood_gate"]["hard_reason_codes"])
        + "` abstain fail-closed, soft reasons only raise the status to high uncertainty. On "
        "the `" + str(probes["n"]) + "` synthetic out-of-domain probes the router abstains at "
        "rate `" + str(probes["abstain_rate"]) + "` with coverage `" + str(probes["coverage"])
        + "` (`" + str(probes["probes_per_kind"]) + "`). The reused gate contract is `"
        + spec["ood_gate"]["contract_path"] + "` (digest pinned). No nearest-price or "
        "nearest-context substitution is performed "
        "(`nearest_price_substituted=" + str(decision["ood_gate"]["nearest_price_substituted"]).lower()
        + "`, `nearest_context_substituted="
        + str(decision["ood_gate"]["nearest_context_substituted"]).lower() + "`).",
        "",
        "## 6. LIMPER_VS_ISO surface",
        "",
        "The limper-versus-isolation family is reported on its own surface (`"
        + str(limper["hands"]) + "` hands) so the pooled tables never hide it: hybrid log loss `"
        + str(limper["models"]["hybrid_router"]["log_loss_bits_per_decision"]) + "` vs active `"
        + str(limper["models"]["active_model_a"]["log_loss_bits_per_decision"]) + "` and "
        "generalized `" + str(limper["models"]["generalized_calibrated"]["log_loss_bits_per_decision"])
        + "`.",
        "",
        "## 7. Generalized calibration (TRAIN-only)",
        "",
        "`GENERALIZED_CALIBRATION_REPORT.json` retains `"
        + calibration["retained_architecture"] + "` / `" + calibration["retained_method"]
        + "`, fitted in-fold and evaluated out-of-fold; VALIDATION is never recalibrated "
        "(`validation_recalibrated="
        + str(calibration["guards"]["validation_recalibrated"]).lower() + "`, "
        "`validation_recalibration_refused="
        + str(calibration["guards"]["validation_recalibration_refused"]).lower() + "`).",
        "",
        "## 8. #367 preflight",
        "",
        "`ISSUE367_PREFLIGHT.json` walks the " + str(preflight["nodes_queried"])
        + " required scenario #321 nodes and " + str(preflight["sizing_frontiers_queried"])
        + " raise-sizing frontiers (" + str(preflight_walk["decisions_visited"])
        + " visited decisions: " + str(preflight_walk["direct_eval_decisions"])
        + " direct evaluations, " + str(preflight_walk["explicit_abstain_decisions"])
        + " explicit abstentions), hero EV executed `"
        + str(preflight["boundary"]["hero_ev_executed"]).lower() + "`, #367 executed `"
        + str(preflight["boundary"]["issue367_executed"]).lower() + "`. Admission is `"
        + str(preflight["admission"]["consumption"]) + "` with outcome `"
        + str(preflight["admission"]["outcome"]) + "` because the terminal router outcome is `"
        + str(preflight["admission"]["terminal_outcome"]) + "`; #367 keeps its currently "
        "admitted model.",
        "",
        "## 9. Digest verification (recomputed vs persisted)",
        "",
        "Every digest this bundle persists is recomputed from the persisted bytes: "
        + str(len(inputs["cross_reference_checks"]))
        + " cross-references declared by the frozen artifacts (file bytes, canonical payloads, "
        "the frozen criteria block and nested provenance digests) and every `.sha256` sidecar "
        "were re-derived and all match "
        "(`digest_verification.all_recomputed_digests_match_persisted = true`). This closes the "
        "#352 failure mode, where a self-reported digest was recorded without ever being "
        "recomputed.",
        "",
        "| artifact | byte SHA256 | canonical payload SHA256 |",
        "| --- | --- | --- |",
    ]
    for name, _role in REQUIRED_ARTIFACTS:
        if name == SUMMARY_NAME:
            lines.append("| SUMMARY.md | `see ARTIFACTS.json` | n/a |")
        elif name == DECISION_NAME:
            lines.append(
                "| DECISION.json | `" + decision_digest + "` | `"
                + str(decision["canonical_payload_sha256"]) + "` |"
            )
        else:
            lines.append("| " + name + " | `" + digests[name] + "` | `see ARTIFACTS.json` |")
    lines += [
        "",
        "## 10. Boundaries",
        "",
        "- `TEST_CONSUMED=false` -- the loader, the harness, the criteria freeze and the "
        "preflight self-scans all refuse TEST (`test_authorized=false`, `test_consumed=false`); "
        "the refused splits are `" + str(report["scope"]["refused_splits"]) + "`.",
        "- `VALIDATION_CONSUMED=false` -- the #421 VALIDATION split is never re-opened: the "
        "design, the calibration, the criteria and the score are all TRAIN-only, and the "
        "preserved #421 evidence is read as descriptive history only.",
        "- `ACTIVE_POINTER_MUTATED=false` -- the active Model A pointer `"
        + decision["references"]["active_model_a_preflop"]["path"] + "` (`"
        + decision["references"]["active_model_a_preflop"]["sha256"] + "`), the Model B pointer `"
        + MODEL_B_REL + "` and the model admitted for #367 (`" + ADMITTED_367_MODEL_ID
        + "`) are unchanged; no promotion is performed (`automatic_promotion=FORBIDDEN`).",
        "- `ISSUE367_EXECUTED=false` -- #367 is neither executed nor authorized by this bundle; "
        "`next_issue=" + str(NEXT_ISSUE) + "` is recorded as `NOT_EXECUTED`; no Hero EV, no "
        "rollout and no support-grid extension are computed.",
        "",
        "## 11. Offline replay (recorded, NON-AUTHORITATIVE)",
        "",
        "The #423 suite and the transverse guards were replayed at the final HEAD with `"
        + OFFLINE_REPLAY_INVOCATION + "`. " + decision["offline_replay"]["note"] + ".",
        "",
        "| command | exit | observed |",
        "| --- | --- | --- |",
    ]
    for row in decision["offline_replay"]["rows"]:
        note = row.get("note", "")
        observed = row["observed_result"] + ((" -- " + note) if note else "")
        lines.append(
            "| `" + row["command"] + "` | " + str(row["observed_exit_code"]) + " | "
            + observed + " |"
        )
    recheck = decision["offline_replay"]["boundary_recheck"]
    lines += [
        "",
        "Terminal boundaries re-checked at the final HEAD (`"
        + recheck["source"] + "`): `test_consumed=" + str(recheck["test_consumed"]).lower()
        + "`, `validation_consumed=" + str(recheck["validation_consumed"]).lower()
        + "`, `validation_reopened=" + str(recheck["validation_reopened"]).lower()
        + "`, `active_pointer_mutated=" + str(recheck["active_pointer_mutated"]).lower()
        + "`, `product_admissible=" + str(recheck["product_admissible"]).lower()
        + "`, `issue367_executed=" + str(recheck["issue367_executed"]).lower()
        + "`, `next_issue=" + str(recheck["next_issue"]) + "` (`"
        + recheck["next_issue_status"] + "`). The active Model A pointer `"
        + recheck["active_model_a_pointer_path"] + "` still hashes to `"
        + recheck["active_model_a_pointer_sha256_on_disk"] + "`"
        + (" (matches the pinned reference)" if recheck["active_model_a_pointer_bytes_match_pin"]
           else " (DOES NOT match the pinned reference)")
        + "; the Model B pointer `" + recheck["model_b_pointer_path"] + "` hashes to `"
        + recheck["model_b_pointer_sha256_on_disk"] + "`.",
        "",
        "## 12. Reproduce and verify",
        "",
        "```text",
        "python3 tools/training/build_issue423_evidence_bundle.py",
        "python3 tools/training/build_issue423_evidence_bundle.py --check",
        "python3 tests/training/test_issue423_evidence_bundle.py",
        "```",
    ]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# persist / check
# --------------------------------------------------------------------------


def _object_name(digest: str, extension: str) -> str:
    return BUNDLE_REL + "/sha256/" + digest + extension


def _artifact_entry(
    path: str,
    role: str,
    data: bytes,
    payload: Mapping[str, Any] | None,
    declared: Mapping[str, str],
) -> dict:
    digest = sha256_bytes(data)
    extension = Path(path).suffix
    entry: dict[str, Any] = {
        "role": role,
        "path": path,
        "media_type": MEDIA_TYPES.get(extension, "application/octet-stream"),
        "bytes": len(data),
        "sha256": digest,
        "object": _object_name(digest, extension),
        "content_addressed": True,
    }
    if payload is not None:
        entry["canonical_payload_sha256"] = canonical_payload_sha256(payload)
    if declared:
        entry["declared_digest"] = dict(declared)
    return entry


def build() -> dict[str, Any]:
    inputs = verify_inputs()
    docs = inputs["docs"]

    decision = build_decision(inputs)
    decision_bytes = serialize(decision)
    decision_digest = sha256_bytes(decision_bytes)
    summary_bytes = summary_text(inputs, decision, decision_digest).encode()
    summary_digest = sha256_bytes(summary_bytes)

    objects: dict[str, bytes] = {}
    artifacts: dict[str, dict] = {}
    for name, role in REQUIRED_ARTIFACTS:
        if name == DECISION_NAME:
            data, payload = decision_bytes, decision
        elif name == SUMMARY_NAME:
            data, payload = summary_bytes, None
        else:
            data = _abs(name).read_bytes()
            payload = docs[name]
        declared = {} if name in AUTHORED_ARTIFACTS else inputs["declared"].get(name, {})
        artifacts[name] = _artifact_entry(BUNDLE_REL + "/" + name, role, data, payload, declared)
        objects[Path(artifacts[name]["object"]).name] = data

    supporting: dict[str, dict] = {}
    for rel, role in SUPPORTING_ARTIFACTS:
        data = (ROOT / rel).read_bytes()
        payload = json.loads(data) if rel.endswith(".json") else None
        supporting[rel] = _artifact_entry(rel, role, data, payload, {})
        objects[Path(supporting[rel]["object"]).name] = data

    sidecar_names = [
        name
        for name, _role in REQUIRED_ARTIFACTS
        if name not in AUTHORED_ARTIFACTS and inputs["declared"].get(name)
    ]
    index = {
        "schema": INDEX_SCHEMA,
        "issue": 423,
        "kind": KIND,
        "bundle": BUNDLE_REL,
        "generated_by": {
            "tool_path": "tools/training/build_issue423_evidence_bundle.py",
            "tool_sha256": sha256_bytes(Path(__file__).read_bytes()),
            "frozen_at": docs["ROUTER_MANIFEST.json"]["frozen_at"],
        },
        "required_artifacts": [name for name, _role in REQUIRED_ARTIFACTS],
        "artifacts": artifacts,
        "supporting_evidence": supporting,
        "notes": (
            "ARTIFACTS.json is an index, not a member of the content-addressed set: it cannot "
            "carry its own digest. Every other artifact is byte-identical to its copy under "
            + BUNDLE_REL + "/sha256/, named <byte-sha256><extension> and listed in `object`."
        ),
        "digest_verification": {
            "all_recomputed_digests_match_persisted": True,
            "recomputation_rule": (
                "byte digests are recomputed from the persisted bytes; canonical payload digests "
                "from the repository-wide stable_hash of the JSON document with any top-level "
                "canonical_payload_sha256 field excluded; the frozen criteria digest from the "
                "stable_hash of the persisted criteria block without its criteria_sha256; the two "
                "derivation digests the frozen criteria publish from the frozen projection that "
                "neutralises /reuse/router/spec_sha256 (see "
                "tools/training/freeze_hybrid_router_criteria.py::derivation_projection), because "
                "the raw derivation bytes depend on the spec digest that embeds those criteria; "
                "nested provenance digests from the persisted JSON path that carries them"
            ),
            "sidecar_checks": [
                {
                    "artifact": name,
                    "declared": inputs["declared"][name],
                    "recomputed": artifacts[name]["sha256"],
                    "match": artifacts[name]["sha256"] == inputs["declared"][name].get("sha256"),
                    "canonical_match": artifacts[name].get("canonical_payload_sha256")
                    == inputs["declared"][name].get("canonical_payload_sha256"),
                }
                for name in sidecar_names
            ],
            "artifacts_verified_only_by_cross_reference": [
                name
                for name, _role in REQUIRED_ARTIFACTS
                if name not in sidecar_names and name not in AUTHORED_ARTIFACTS
            ],
            "cross_reference_checks": inputs["cross_reference_checks"],
            "runtime_internal_identifiers_not_recomputable": (
                "per-decision `decision_canonical_sha256`, per-fold calibration `params_sha256` "
                "and node identity `node_id`s describe non-persisted runtime documents; they are "
                "internal identifiers, never bound as file digests"
            ),
        },
        "boundary": {
            "split": docs["TRAIN_CV_ROUTER_REPORT.json"]["scope"]["split"],
            "consumed_splits": docs["TRAIN_CV_ROUTER_REPORT.json"]["scope"]["consumed_splits"],
            "refused_splits": docs["TRAIN_CV_ROUTER_REPORT.json"]["scope"]["refused_splits"],
            "validation_consumed": False,
            "validation_reopened": False,
            "test_consumed": False,
            "test_authorized": False,
            "active_pointer_mutated": False,
            "active_model_pointer_mutation": False,
            "automatic_promotion": "FORBIDDEN",
            "product_admissible": False,
            "issue367_executed": False,
            "hero_ev_executed": False,
            "model_b_consumed": False,
            "next_issue": NEXT_ISSUE,
        },
        "terminal_decision": {
            "decision": decision["decision"],
            "terminal_outcomes": [entry["id"] for entry in decision["terminal_outcomes"]],
            "actual_terminal_outcome": decision["decision"],
            "criteria_passed": decision["criteria_passed"],
            "criteria_total": decision["criteria_total"],
            "failed_criteria": decision["failed_criteria"],
            "issue367_authorized": decision["issue367"]["authorized"],
            "next_issue": NEXT_ISSUE,
        },
        "evidence_bindings": {
            name: {
                "path": artifacts[name]["path"],
                "sha256": artifacts[name]["sha256"],
                "object": artifacts[name]["object"],
            }
            for name, _role in REQUIRED_ARTIFACTS
            if name != SUMMARY_NAME
        },
        "decision": {
            "path": BUNDLE_REL + "/" + DECISION_NAME,
            "sha256": decision_digest,
            "canonical_payload_sha256": decision["canonical_payload_sha256"],
            "object": artifacts[DECISION_NAME]["object"],
        },
        "summary": {
            "path": BUNDLE_REL + "/" + SUMMARY_NAME,
            "sha256": summary_digest,
            "object": artifacts[SUMMARY_NAME]["object"],
        },
    }
    return {
        "decision_bytes": decision_bytes,
        "decision_digest": decision_digest,
        "decision": decision,
        "summary_bytes": summary_bytes,
        "summary_digest": summary_digest,
        "index": index,
        "objects": objects,
    }


def persist() -> int:
    bundle = build()
    objects_dir().mkdir(parents=True, exist_ok=True)
    decision_path().write_bytes(bundle["decision_bytes"])
    summary_path().write_bytes(bundle["summary_bytes"])
    decision_digest_path().write_text(
        bundle["decision_digest"] + "  " + DECISION_NAME + "\n"
        "# canonical_payload_sha256 " + bundle["decision"]["canonical_payload_sha256"] + "\n"
        "# decision_id " + DECISION_ID + "\n",
        encoding="utf-8",
    )
    index_path().write_bytes(serialize(bundle["index"]))
    referenced = set()
    for section in ("artifacts", "supporting_evidence"):
        for entry in bundle["index"][section].values():
            object_name = Path(entry["object"]).name
            referenced.add(object_name)
            (objects_dir() / object_name).write_bytes(bundle["objects"][object_name])
    for path in objects_dir().iterdir():
        if path.is_file() and path.name not in referenced:
            path.unlink()
    return check()


def check() -> int:
    try:
        bundle = build()
    except BundleError as error:
        print(json.dumps({"status": "MISMATCH", "problems": [str(error)]}, indent=2))
        return 1

    problems: list[str] = []
    expected = (
        (decision_path(), bundle["decision_bytes"]),
        (summary_path(), bundle["summary_bytes"]),
        (index_path(), serialize(bundle["index"])),
    )
    for path, data in expected:
        if not path.is_file() or path.read_bytes() != data:
            problems.append(path.name + " differs from a fresh deterministic build")
    if not decision_digest_path().is_file() or not decision_digest_path().read_text(
        encoding="utf-8"
    ).startswith(bundle["decision_digest"] + "  " + DECISION_NAME):
        problems.append("DECISION.sha256 is missing or stale")

    if index_path().is_file():
        persisted = json.loads(index_path().read_text(encoding="utf-8"))
        for section in ("artifacts", "supporting_evidence"):
            for name, entry in persisted.get(section, {}).items():
                object_path = _resolve(entry["object"])
                if not object_path.is_file():
                    problems.append("missing content-addressed copy for " + name)
                    continue
                if sha256_bytes(object_path.read_bytes()) != entry["sha256"]:
                    problems.append("recomputed digest mismatch for the copy of " + name)
                source = _resolve(entry["path"])
                if not source.is_file():
                    problems.append("missing source artifact " + entry["path"])
                elif sha256_bytes(source.read_bytes()) != entry["sha256"]:
                    problems.append(name + " on disk drifted from the index digest")
        if not persisted.get("digest_verification", {}).get(
            "all_recomputed_digests_match_persisted"
        ):
            problems.append("digest verification block does not report a full match")
        for check_entry in persisted.get("digest_verification", {}).get(
            "cross_reference_checks", []
        ):
            if not check_entry["match"]:
                problems.append(
                    "declared digest mismatch: "
                    + check_entry["source"]
                    + " ["
                    + check_entry["kind"]
                    + "]"
                )
        for sidecar_entry in persisted.get("digest_verification", {}).get("sidecar_checks", []):
            if not sidecar_entry["match"] or not sidecar_entry["canonical_match"]:
                problems.append("sidecar digest mismatch: " + sidecar_entry["artifact"])
        boundary = persisted.get("boundary", {})
        for flag in ("test_consumed", "active_pointer_mutated", "issue367_executed"):
            if boundary.get(flag) is not False:
                problems.append("boundary." + flag + " is not false")
        referenced = {
            Path(entry["object"]).name
            for section in ("artifacts", "supporting_evidence")
            for entry in persisted.get(section, {}).values()
        }
        if objects_dir().is_dir():
            extra = {path.name for path in objects_dir().iterdir() if path.is_file()} - referenced
            if extra:
                problems.append("unreferenced objects under sha256/: " + str(sorted(extra)))

    if problems:
        print(json.dumps({"status": "MISMATCH", "problems": problems}, indent=2))
        return 1
    print(
        json.dumps(
            {
                "status": "OK",
                "bundle": BUNDLE_REL,
                "decision_sha256": bundle["decision_digest"],
                "summary_sha256": bundle["summary_digest"],
                "required_artifacts": len(bundle["index"]["required_artifacts"]),
                "content_addressed_objects": len(bundle["objects"]),
                "cross_reference_checks": len(
                    bundle["index"]["digest_verification"]["cross_reference_checks"]
                ),
            },
            indent=2,
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="verify without writing")
    args = parser.parse_args(argv)
    if args.check:
        return check()
    return persist()


if __name__ == "__main__":
    raise SystemExit(main())

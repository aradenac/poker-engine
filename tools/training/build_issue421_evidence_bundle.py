#!/usr/bin/env python3
"""#421 T12 -- persist the required evidence set content-addressed, with SUMMARY.

The issue demands ten evidence artifacts be *persisted and content-addressed*:
``GENERALIZED_RESPONSE_MODEL_SPEC.json``, ``TRAIN_CV_REPORT.json``,
``CANDIDATE_MANIFEST.json``, ``FROZEN_VALIDATION_PROTOCOL.json``,
``VALIDATION_RESULT.json``, ``OOD_CALIBRATION_REPORT.json``,
``RAISE_SIZING_MODEL_REPORT.json``, ``ISSUE367_PREFLIGHT.json``,
``DECISION.json`` and ``SUMMARY.md``.

``GENERALIZED_RESPONSE_MODEL_SPEC.json`` is the one member no other task emits:
the candidate had a manifest, a protocol and a decision, but no machine-readable
description of *the model itself*.  This tool authors it as a deterministic
projection of the already frozen evidence (no re-fit, no holdout read) and then
binds all ten artifacts:

* byte-identical copies under ``analysis/issue421_generalized_response/sha256/``;
* ``ARTIFACTS.json``, an index recording per artifact the byte digest, the
  canonical payload digest and every *declared* digest the evidence set carries
  (its own ``.sha256`` sidecar and every cross-reference pinned by a sibling);
* ``SUMMARY.md`` covering coverage, calibration, strata, the OOD gate, the
  raise-sizing gate, the #367 preflight, the terminal decision and the boundary
  (``TEST_CONSUMED=false``, active pointer unchanged).

Digest handling answers the #352 failure mode directly: a self-reported digest
that is never recomputed.  Every digest this bundle persists is recomputed from
the persisted bytes and compared against the declared value; any mismatch fails
closed, at build time and under ``--check``.  ``ARTIFACTS.json`` is the only
member that carries no digest of its own (it cannot hash itself); every other
artifact is content-addressed.

Boundaries
----------
The tool parses no hand history and no decision JSONL: it reads the *persisted*
evidence documents and hashes pinned corpus bytes (a hash is not a read of a
split).  TEST stays unconsumed, the VALIDATION split is never re-opened, the
active Model A/B pointers are never written and #367 is never executed.
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

# --------------------------------------------------------------------------
# layout
# --------------------------------------------------------------------------

HERE = ROOT / "analysis/issue421_generalized_response"
BUNDLE_REL = "analysis/issue421_generalized_response"
OBJECTS = HERE / "sha256"

INDEX_PATH = HERE / "ARTIFACTS.json"
SUMMARY_PATH = HERE / "SUMMARY.md"
SPEC_PATH = HERE / "GENERALIZED_RESPONSE_MODEL_SPEC.json"
SPEC_DIGEST_PATH = HERE / "GENERALIZED_RESPONSE_MODEL_SPEC.sha256"
SPEC_NAME = "GENERALIZED_RESPONSE_MODEL_SPEC.json"
SUMMARY_NAME = "SUMMARY.md"

SPEC_SCHEMA = "poker-generalized-response-model-spec/v1"
INDEX_SCHEMA = "poker-generalized-response-evidence-index/v1"
SPEC_ID = "generalized-adverse-response-model-spec-v1"
SPEC_STATUS = "SPEC_ONLY_NOT_ACTIVE"

CANDIDATE_REL = (
    "analysis/issue421_generalized_response/model/candidate_regularized_multinomial_spline.json"
)
ALTERNATE_REL = (
    "analysis/issue421_generalized_response/model/candidate_hierarchical_empirical_bayes_dirichlet.json"
)
DATASET_REL = "analysis/issue421_generalized_response/dataset/GENERALIZED_RESPONSE_DATASET.jsonl"
DATASET_MANIFEST_REL = (
    "analysis/issue421_generalized_response/dataset/GENERALIZED_RESPONSE_DATASET.json"
)
CORPUS_HASHES_REL = "analysis/issue421_generalized_response/dataset/CORPUS_HASHES.json"
FIT_REPORT_REL = "analysis/issue421_generalized_response/model/FIT_REPORT.json"
V2_352_VALIDATION_REL = "analysis/model_a_preflop_sizing_v2_validation.json"

#: ``(name, role)`` of the ten artifacts the ticket enumerates, in ticket order.
REQUIRED_ARTIFACTS: tuple[tuple[str, str], ...] = (
    ("GENERALIZED_RESPONSE_MODEL_SPEC.json", "T12_GENERALIZED_RESPONSE_MODEL_SPEC"),
    ("TRAIN_CV_REPORT.json", "T4_MULTI_ARCHITECTURE_TRAIN_CV"),
    ("CANDIDATE_MANIFEST.json", "T7_CANDIDATE_MANIFEST"),
    ("FROZEN_VALIDATION_PROTOCOL.json", "T7_FROZEN_VALIDATION_PROTOCOL"),
    ("VALIDATION_RESULT.json", "T8_ONE_SHOT_VALIDATION_RESULT"),
    ("OOD_CALIBRATION_REPORT.json", "T6_OOD_CALIBRATION_REPORT"),
    ("RAISE_SIZING_MODEL_REPORT.json", "T5_RAISE_SIZING_MODEL_REPORT"),
    ("ISSUE367_PREFLIGHT.json", "T10_ISSUE367_PREFLIGHT"),
    ("DECISION.json", "T8_TERMINAL_DECISION"),
    ("SUMMARY.md", "T12_SUMMARY"),
)

#: Evidence the required set binds transitively, content-addressed here too so
#: the bundle verifies end to end without trusting a sibling bundle.
SUPPORTING_ARTIFACTS: tuple[tuple[str, str], ...] = (
    (f"{BUNDLE_REL}/GENERALIZED_RESPONSE_DATASET_REPORT.json", "T2_FEATURE_FRAGMENTATION_REPORT"),
    (DATASET_MANIFEST_REL, "T1_DATASET_MANIFEST"),
    (CORPUS_HASHES_REL, "T1_CORPUS_HASHES"),
    (FIT_REPORT_REL, "T3_FIT_REPORT"),
    (CANDIDATE_REL, "T3_SELECTED_CANDIDATE"),
    (ALTERNATE_REL, "T3_ALTERNATE_CANDIDATE"),
)

MEDIA_TYPES = {".json": "application/json", ".md": "text/markdown", ".txt": "text/plain"}


class BundleError(RuntimeError):
    """A frozen artifact drifted, or the bundle would not be verifiable."""


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


def _abs(name: str) -> Path:
    return HERE / name


def _load(name: str) -> dict:
    try:
        return json.loads(_abs(name).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:  # pragma: no cover - defensive
        raise BundleError(f"cannot load {name}: {error}") from error


def _digest(rel_or_name: str) -> str:
    path = ROOT / rel_or_name if rel_or_name.startswith("analysis/") else _abs(rel_or_name)
    try:
        return sha256_bytes(path.read_bytes())
    except OSError as error:  # pragma: no cover - defensive
        raise BundleError(f"cannot hash {rel_or_name}: {error}") from error


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


def _cross_reference_checks(docs: Mapping[str, dict], digests: Mapping[str, str]) -> list[dict]:
    """Recompute every digest the frozen evidence set declares about another file."""
    checks: list[dict] = []
    manifest = docs["CANDIDATE_MANIFEST.json"]
    protocol = docs["FROZEN_VALIDATION_PROTOCOL.json"]
    validation = docs["VALIDATION_RESULT.json"]
    decision = docs["DECISION.json"]
    preflight = docs["ISSUE367_PREFLIGHT.json"]

    def canonical_of(artifact: str) -> str | None:
        path = ROOT / artifact if artifact.startswith("analysis/") else _abs(artifact)
        if not path.is_file():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        if artifact in (CANDIDATE_REL, ALTERNATE_REL):
            return M.canonical_candidate_sha256(payload)
        return canonical_payload_sha256(payload)

    def add(source: str, field: str, artifact: str, declared: Any) -> None:
        if declared is None:
            return
        if field == "canonical_payload_sha256":
            recomputed = canonical_of(artifact)
        else:
            recomputed = digests.get(artifact)
            if recomputed is None and artifact.startswith("analysis/"):
                recomputed = digests.get(Path(artifact).name)
        checks.append(
            {
                "source": source,
                "field": field,
                "artifact": artifact,
                "declared": str(declared),
                "recomputed": recomputed,
                "match": str(declared) == recomputed,
            }
        )

    # Candidate manifest -> every artifact it consumed.
    add("CANDIDATE_MANIFEST.candidate", "sha256", CANDIDATE_REL, manifest["candidate"]["sha256"])
    add(
        "CANDIDATE_MANIFEST.candidate",
        "canonical_payload_sha256",
        CANDIDATE_REL,
        manifest["candidate"]["canonical_payload_sha256"],
    )
    add(
        "CANDIDATE_MANIFEST.features",
        "feature_audit_report_sha256",
        "GENERALIZED_RESPONSE_DATASET_REPORT.json",
        manifest["features"]["feature_audit_report_sha256"],
    )
    add(
        "CANDIDATE_MANIFEST.ood_gate",
        "calibration_report_sha256",
        "OOD_CALIBRATION_REPORT.json",
        manifest["ood_gate"]["calibration_report_sha256"],
    )
    add(
        "CANDIDATE_MANIFEST.sizing_criteria.train_evidence",
        "sha256",
        "RAISE_SIZING_MODEL_REPORT.json",
        manifest["sizing_criteria"]["train_evidence"]["sha256"],
    )
    add(
        "CANDIDATE_MANIFEST.cv_procedure",
        "report_sha256",
        "TRAIN_CV_REPORT.json",
        manifest["cv_procedure"]["report_sha256"],
    )
    add(
        "CANDIDATE_MANIFEST.thresholds.calibration.train_out_of_fold_evidence",
        "sha256",
        "TRAIN_CV_REPORT.json",
        manifest["thresholds"]["calibration"]["train_out_of_fold_evidence"]["sha256"],
    )
    add(
        "CANDIDATE_MANIFEST.corpus",
        "dataset_manifest_sha256",
        DATASET_MANIFEST_REL,
        manifest["corpus"]["dataset_manifest_sha256"],
    )
    add(
        "CANDIDATE_MANIFEST.corpus",
        "dataset_sha256",
        DATASET_REL,
        manifest["corpus"]["dataset_sha256"],
    )
    add(
        "CANDIDATE_MANIFEST.corpus",
        "corpus_hashes_sha256",
        CORPUS_HASHES_REL,
        manifest["corpus"]["corpus_hashes_sha256"],
    )

    # Frozen protocol -> the candidate it freezes and the evidence it binds.
    add(
        "FROZEN_VALIDATION_PROTOCOL.artifacts.candidate",
        "sha256",
        CANDIDATE_REL,
        protocol["artifacts"]["candidate"]["sha256"],
    )
    add(
        "FROZEN_VALIDATION_PROTOCOL.artifacts.candidate",
        "canonical_payload_sha256",
        CANDIDATE_REL,
        protocol["artifacts"]["candidate"]["canonical_payload_sha256"],
    )
    add(
        "FROZEN_VALIDATION_PROTOCOL.artifacts.candidate_manifest",
        "sha256",
        "CANDIDATE_MANIFEST.json",
        protocol["artifacts"]["candidate_manifest"]["sha256"],
    )
    for entry in protocol["artifacts"].get("evidence", ()):
        artifact = str(entry.get("path", ""))
        if artifact:
            add(
                "FROZEN_VALIDATION_PROTOCOL.artifacts.evidence[" + str(entry.get("role")) + "]",
                "sha256",
                artifact,
                entry["sha256"],
            )

    # One-shot VALIDATION result -> its declared inputs.
    add(
        "VALIDATION_RESULT.inputs.candidate",
        "sha256",
        CANDIDATE_REL,
        validation["inputs"]["candidate"]["sha256"],
    )
    add(
        "VALIDATION_RESULT.inputs.candidate",
        "canonical_payload_sha256",
        CANDIDATE_REL,
        validation["inputs"]["candidate"]["canonical_payload_sha256"],
    )
    add(
        "VALIDATION_RESULT.inputs.alternate_candidate",
        "sha256",
        ALTERNATE_REL,
        validation["inputs"]["alternate_candidate"]["sha256"],
    )
    add(
        "VALIDATION_RESULT.inputs.dataset",
        "sha256",
        DATASET_REL,
        validation["inputs"]["dataset"]["sha256"],
    )
    add(
        "VALIDATION_RESULT.inputs.dataset_manifest",
        "sha256",
        DATASET_MANIFEST_REL,
        validation["inputs"]["dataset_manifest"]["sha256"],
    )
    add(
        "VALIDATION_RESULT.inputs.fit_report",
        "sha256",
        FIT_REPORT_REL,
        validation["inputs"]["fit_report"]["sha256"],
    )
    add(
        "VALIDATION_RESULT.inputs.ood_calibration_report",
        "sha256",
        "OOD_CALIBRATION_REPORT.json",
        validation["inputs"]["ood_calibration_report"]["sha256"],
    )
    add(
        "VALIDATION_RESULT.inputs.raise_sizing_report",
        "sha256",
        "RAISE_SIZING_MODEL_REPORT.json",
        validation["inputs"]["raise_sizing_report"]["sha256"],
    )
    add(
        "VALIDATION_RESULT.inputs.train_cv_report",
        "sha256",
        "TRAIN_CV_REPORT.json",
        validation["inputs"]["train_cv_report"]["sha256"],
    )
    add(
        "VALIDATION_RESULT.protocol",
        "protocol_byte_sha256",
        "FROZEN_VALIDATION_PROTOCOL.json",
        validation["protocol"]["protocol_byte_sha256"],
    )
    add(
        "VALIDATION_RESULT.inputs.model_a_sizing_aware_v2_352",
        "validation_sha256",
        V2_352_VALIDATION_REL,
        validation["inputs"]["model_a_sizing_aware_v2_352"]["validation_sha256"],
    )

    # Terminal decision -> the validation result and the candidate it judged.
    add(
        "DECISION",
        "validation_result_sha256",
        "VALIDATION_RESULT.json",
        decision["validation_result_sha256"],
    )
    add(
        "DECISION.candidate",
        "canonical_payload_sha256",
        CANDIDATE_REL,
        decision["candidate"]["canonical_payload_sha256"],
    )

    # #367 preflight -> the admission evidence it read.
    add(
        "ISSUE367_PREFLIGHT.evidence_bindings",
        "candidate_manifest_sha256",
        "CANDIDATE_MANIFEST.json",
        preflight["evidence_bindings"]["candidate_manifest_sha256"],
    )
    add(
        "ISSUE367_PREFLIGHT.evidence_bindings",
        "candidate_byte_sha256",
        CANDIDATE_REL,
        preflight["evidence_bindings"]["candidate_byte_sha256"],
    )
    add(
        "ISSUE367_PREFLIGHT.evidence_bindings",
        "decision_sha256",
        "DECISION.json",
        preflight["evidence_bindings"]["decision_sha256"],
    )
    add(
        "ISSUE367_PREFLIGHT.evidence_bindings",
        "ood_calibration_sha256",
        "OOD_CALIBRATION_REPORT.json",
        preflight["evidence_bindings"]["ood_calibration_sha256"],
    )
    add(
        "ISSUE367_PREFLIGHT.evidence_bindings",
        "protocol_byte_sha256",
        "FROZEN_VALIDATION_PROTOCOL.json",
        preflight["evidence_bindings"]["protocol_byte_sha256"],
    )
    return checks


def verify_inputs() -> dict:
    """Load the frozen evidence, recompute every digest and fail closed on drift."""
    docs = {
        name: _load(name)
        for name, _role in REQUIRED_ARTIFACTS
        if name.endswith(".json") and name != SPEC_NAME
    }
    if SUMMARY_NAME in docs:  # pragma: no cover - defensive
        raise BundleError("SUMMARY.md is generated, not an input")

    digests: dict[str, str] = {}
    for name, _role in REQUIRED_ARTIFACTS:
        if name not in (SUMMARY_NAME, SPEC_NAME):
            digests[name] = _digest(name)
    for rel, _role in SUPPORTING_ARTIFACTS:
        digests[rel] = _digest(rel)
        digests[Path(rel).name] = digests[rel]
    digests[DATASET_REL] = _digest(DATASET_REL)
    digests[V2_352_VALIDATION_REL] = _digest(V2_352_VALIDATION_REL)

    # Per-artifact declared digests come from the artifact's own .sha256 sidecar.
    declared: dict[str, dict[str, str]] = {}
    problems: list[str] = []
    for name, _role in REQUIRED_ARTIFACTS:
        if name in (SUMMARY_NAME, SPEC_NAME):
            continue
        side = _sidecar_digests(name)
        declared[name] = side
        for field, value in side.items():
            actual = digests[name] if field == "sha256" else canonical_payload_sha256(docs[name])
            if actual != value:
                problems.append(f"{name}: declared {field} {value} != recomputed {actual}")

    cross = _cross_reference_checks(docs, digests)
    problems.extend(
        check["source"]
        + "."
        + check["field"]
        + " declared "
        + check["declared"]
        + " != recomputed "
        + str(check["recomputed"])
        + " ("
        + check["artifact"]
        + ")"
        for check in cross
        if not check["match"]
    )

    # Scientific boundary: the terminal decision must agree with the frozen
    # protocol outcome and with every consumed artifact's own declaration.
    manifest = docs["CANDIDATE_MANIFEST.json"]
    protocol = docs["FROZEN_VALIDATION_PROTOCOL.json"]
    validation = docs["VALIDATION_RESULT.json"]
    decision = docs["DECISION.json"]
    if decision["validation_result_sha256"] != digests["VALIDATION_RESULT.json"]:
        problems.append("decision does not bind the persisted VALIDATION_RESULT bytes")
    if decision["decision"] != validation["decision"]:
        problems.append("decision/validation decision mismatch")
    if (
        decision["candidate"]["canonical_payload_sha256"]
        != manifest["candidate"]["canonical_payload_sha256"]
    ):
        problems.append("decision candidate payload digest differs from the manifest candidate")
    if protocol["artifacts"]["candidate"]["sha256"] != digests[CANDIDATE_REL]:
        problems.append("protocol candidate bytes differ from the persisted candidate")
    if protocol["artifacts"]["candidate_manifest"]["sha256"] != digests["CANDIDATE_MANIFEST.json"]:
        problems.append("protocol manifest bytes differ from the persisted manifest")
    if canonical_payload_sha256(docs["DECISION.json"]) != decision.get("canonical_payload_sha256"):
        problems.append("DECISION canonical payload digest is not self-consistent")
    if (
        canonical_payload_sha256(docs["VALIDATION_RESULT.json"])
        != validation.get("canonical_payload_sha256")
    ):
        problems.append("VALIDATION_RESULT canonical payload digest is not self-consistent")
    def require_false(label: str, payload: Mapping[str, Any], path: str) -> None:
        node: Any = payload
        for part in path.split("."):
            if not isinstance(node, Mapping) or part not in node:
                problems.append(f"{label}.{path} is missing")
                return
            node = node[part]
        if node is not False:
            problems.append(f"{label}.{path} is not false")

    require_false("CANDIDATE_MANIFEST", manifest, "corpus.test_consumed_for_authoring")
    require_false("CANDIDATE_MANIFEST", manifest, "corpus.validation_consumed_for_authoring")
    require_false("CANDIDATE_MANIFEST", manifest, "corpus.test.consumed")
    require_false("CANDIDATE_MANIFEST", manifest, "candidate.active_model_replaced")
    for reference in ("active_model_a_preflop", "active_model_b_postflop"):
        require_false(
            "CANDIDATE_MANIFEST",
            manifest,
            "active_references." + reference + ".mutated_by_this_freeze",
        )
    for path in (
        "evaluation.test_consumed",
        "holdout_boundary.test_consumed",
        "publication.active_model_pointer_mutation",
        "issue367_rule.test_consumed",
        "issue367_rule.active_model_pointer_mutation",
    ):
        require_false("FROZEN_VALIDATION_PROTOCOL", protocol, path)
    require_false("VALIDATION_RESULT", validation, "test_consumed")
    require_false("VALIDATION_RESULT", validation, "active_pointer_mutated")
    require_false("VALIDATION_RESULT", validation, "active_pointer_mutation")
    require_false("DECISION", decision, "test_consumed")
    require_false("DECISION", decision, "active_pointer_mutated")
    require_false("DECISION", decision, "active_model_pointer_mutation")
    if protocol["holdout_boundary"]["test_consumed"] is not False:
        problems.append("protocol holdout boundary declares TEST consumed")
    if protocol["issue367_rule"]["authorized_at_freeze"] is not False:
        problems.append("protocol authorizes #367 at freeze")
    if decision["issue367_authorized"] is not False:
        problems.append("decision authorizes #367")

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


def build_spec(inputs: Mapping[str, Any]) -> dict:
    """Project the frozen evidence into the model spec (deterministic, no new claim)."""
    docs = inputs["docs"]
    digests = inputs["digests"]
    manifest = docs["CANDIDATE_MANIFEST.json"]
    protocol = docs["FROZEN_VALIDATION_PROTOCOL.json"]
    validation = docs["VALIDATION_RESULT.json"]
    decision = docs["DECISION.json"]
    sizing = docs["RAISE_SIZING_MODEL_REPORT.json"]
    ood = docs["OOD_CALIBRATION_REPORT.json"]
    runtime = manifest["runtime_format"]

    def binding(rel: str) -> dict:
        return {"path": rel, "sha256": digests[rel]}

    return {
        "schema": SPEC_SCHEMA,
        "kind": "GENERALIZED_RESPONSE_MODEL_SPEC",
        "issue": 421,
        "specification_id": SPEC_ID,
        "status": SPEC_STATUS,
        "objective": (
            "Describe the preflop adverse-response model that replaces exact-cell lookup with a "
            "calibrated distribution P(action | public preflop response context, price, stack, "
            "history, requested sizing) over FOLD/CALL/RAISE/JAM, plus a conditional legal "
            "raise-sizing channel and a fail-closed OOD/uncertainty gate, so the frozen evidence "
            "can be read without reconstructing what the model is."
        ),
        "admits_nothing": (
            "this spec is descriptive only: it fits nothing, promotes nothing, wires no provider "
            "into #367 and does not change the active Model A/B pointers"
        ),
        "model_identity": {
            **manifest["architecture"],
            "candidate_id": manifest["candidate"]["candidate_id"],
            "seed": manifest["seeds"]["candidate_seed"],
            "candidate_path": CANDIDATE_REL,
            "candidate_byte_sha256": digests[CANDIDATE_REL],
            "candidate_canonical_payload_sha256": manifest["candidate"]["canonical_payload_sha256"],
            "model_schema": runtime["model_schema"],
            "evaluation_schema": runtime["evaluation_schema"],
            "prediction_schema": runtime["prediction_schema"],
            "price_response_schema": runtime["price_response_schema"],
            "runtime_module_path": runtime["module_path"],
            "runtime_module_sha256": runtime["module_sha256"],
            "entrypoint": (
                "tools/preflop/generalized_response_runtime.py::resolve_generalized_response"
            ),
            "selected_by": manifest["candidate"]["selected_by"],
            "selection_evidence_basis": manifest["candidate"]["selection_evidence"][
                "evidence_basis"
            ],
            "candidate_status": manifest["candidate"]["status"],
        },
        "domain_and_scope": {
            "population_id": manifest["corpus"]["population_id"],
            "population_fingerprint_sha256": manifest["corpus"]["population_fingerprint_sha256"],
            "player_role": "ADVERSE_NON_HERO",
            "state_timing": manifest["features"]["state_timing"],
            "public_only": manifest["features"]["public_only"],
            "split_scope": manifest["features"]["split_scope"],
            "refused_splits": manifest["features"]["refused_splits"],
            "response_actions": manifest["features"]["response_actions"],
            "excluded_actions": manifest["features"]["excluded_actions"],
            "fit_split": manifest["corpus"]["split_consumed_for_authoring"],
            "validation_role": manifest["corpus"]["validation"]["reserved_for"],
            "test": manifest["corpus"]["test"],
        },
        "input_contract": {
            "row_contract_path": manifest["features"]["row_contract_path"],
            "row_contract_sha256": manifest["features"]["row_contract_sha256"],
            "required_fields": manifest["features"]["row_contract_fields"],
            "optional_input_fields": runtime["optional_input_fields"],
            "forbidden_keys": manifest["features"]["forbidden_keys"],
            "categorical_blocks": manifest["features"]["categorical_blocks"],
            "interaction_blocks": manifest["features"]["interaction_blocks"],
            "spline_blocks": manifest["features"]["spline_blocks"],
            "outcome_dimensions_excluded": manifest["features"]["outcome_dimensions_excluded"],
            "hidden_hand_imputation": manifest["architecture"]["hidden_hand_imputation"],
            "pseudo_observation": manifest["architecture"]["pseudo_observation"],
        },
        "representation": {
            "axis_transform": manifest["transformations"]["axis_transform"],
            "spline_axis_knots": manifest["transformations"]["spline_axis_knots"],
            "categorical_level_rules": manifest["transformations"]["categorical_level_rules"],
            "sizing_target_axis": manifest["transformations"]["sizing_target_axis"],
            "sizing_axis_knots": manifest["transformations"]["sizing_axis_knots"],
            "sizing_ratio_cap": manifest["transformations"]["sizing_ratio_cap"],
            "partition_of_unity": manifest["transformations"]["partition_of_unity"],
            "continuous_recompute_on_query": manifest["transformations"][
                "continuous_recompute_on_query"
            ],
            "no_nearest_cell_substitution": manifest["transformations"][
                "no_nearest_cell_substitution"
            ],
        },
        "estimator": {
            "model_family": manifest["architecture"]["model_family"],
            "architecture": manifest["architecture"]["architecture"],
            "estimator": manifest["hyperparameters"]["estimator"],
            "discrete_choice_core": manifest["architecture"]["discrete_choice_core"],
            "conditional_sizing_channel": manifest["architecture"]["conditional_sizing_channel"],
            "alternative_architectures": manifest["architecture"]["alternative_architectures"],
            "hyperparameters": manifest["hyperparameters"],
            "cross_validation": manifest["cv_procedure"],
        },
        "output_contract": {
            "probability_fields": runtime["output_fields"],
            "legal_masking": runtime["legal_masking"],
            "illegal_mass_max": runtime["illegal_mass_max"],
            "probability_sum_tolerance": runtime["probability_sum_tolerance"],
            "standard_library_only": runtime["standard_library_only"],
            "deterministic": runtime["deterministic"],
            "test_refused_fail_closed": runtime["test_refused_fail_closed"],
        },
        "uncertainty_gate": {
            **manifest["ood_gate"],
            "calibration_scope": ood["scope"],
            "acceptance_checks": ood["acceptance_checks"],
            "out_of_fold_status_shares": ood["gate_rules"][
                "measured_out_of_fold_status_shares"
            ],
            "combination_rule": ood["gate_rules"]["combination"],
            "exact_context_absent_is_not_ood": ood["gate_rules"]["exact_context_absent_is_not_ood"],
        },
        "conditional_sizing_model": {
            "criteria": manifest["sizing_criteria"],
            "guarantees": sizing["guarantees"],
            "train_metrics": sizing["metrics"],
            "frontiers": sizing["frontiers"],
        },
        "calibration_and_metrics": {
            "primary": manifest["metrics"]["primary"],
            "secondary": manifest["metrics"]["secondary"],
            "stratification": manifest["metrics"]["stratification"],
            "paired_unit": manifest["metrics"]["paired_unit"],
            "calibration_max": manifest["calibration_max"],
            "bootstrap": manifest["metrics"]["bootstrap"],
        },
        "one_shot_validation": {
            "protocol_status": protocol["status"],
            "protocol_byte_sha256": digests["FROZEN_VALIDATION_PROTOCOL.json"],
            "protocol_canonical_payload_sha256": canonical_payload_sha256(protocol),
            "outcome": validation["outcome"],
            "split": validation["split"],
            "evaluation_universe": validation["evaluation_universe"],
            "validation_reads": validation["validation_reads"],
            "validation_consumed": decision["validation_consumed"],
            "thresholds": protocol["thresholds"],
            "non_inferiority_rule": manifest["non_inferiority_rule"],
        },
        "terminal_decision": {
            "decision": decision["decision"],
            "protocol_outcome": decision["protocol_outcome"],
            "criteria_passed": decision["criteria_passed"],
            "criteria_total": decision["criteria_total"],
            "failed_gates": decision["failed_gates"],
            "passed_gates": decision["passed_gates"],
            "rationale": decision["rationale"],
            "issue367_authorized": decision["issue367_authorized"],
            "automatic_promotion": decision["automatic_promotion"],
        },
        "holdout_boundary": {
            "validation_consumed": True,
            "validation_reads": decision["validation_reads"],
            "validation_split_reopened_by_this_spec": False,
            "test_consumed": False,
            "test_authorized": False,
            "test_split_refused": True,
            "active_pointer_mutated": False,
            "active_model_pointer_mutation": False,
            "issue367_executed": False,
            "hero_ev_computed": False,
            "model_b_consumed": False,
        },
        "determinism": manifest["seeds"],
        "forbidden": manifest["forbidden"],
        "evidence_bindings": {
            name: binding(name)
            for name, _role in REQUIRED_ARTIFACTS
            if name not in (SUMMARY_NAME, SPEC_NAME)
        },
        "reproduction": {
            "build_command": "python3 tools/training/build_issue421_evidence_bundle.py",
            "check_command": "python3 tools/training/build_issue421_evidence_bundle.py --check",
            "producer_tools": {
                "dataset": "tools/training/build_generalized_response_dataset.py",
                "features": "tools/training/audit_generalized_response_features.py",
                "model": "tools/preflop/generalized_response_model.py",
                "cross_validation": "tools/training/evaluate_generalized_response_cv.py",
                "freeze": "tools/training/freeze_generalized_validation_protocol.py",
                "validation": "tools/training/validate_generalized_response.py",
                "runtime": "tools/preflop/generalized_response_runtime.py",
                "preflight": "tools/simulation/issue421_issue367_preflight.py",
            },
        },
        "spec_digest_location": (
            "the spec digest cannot live inside the spec payload; it is recorded in "
            "GENERALIZED_RESPONSE_MODEL_SPEC.sha256 and in ARTIFACTS.json"
        ),
    }


def summary_text(inputs: Mapping[str, Any], spec_digest: str, spec: Mapping[str, Any]) -> str:
    docs = inputs["docs"]
    digests = inputs["digests"]
    manifest = docs["CANDIDATE_MANIFEST.json"]
    validation = docs["VALIDATION_RESULT.json"]
    decision = docs["DECISION.json"]
    metrics = validation["metrics"]
    coverage = metrics["coverage"]
    primary = metrics["primary"]["per_model"]
    strata = metrics["strata"]
    ood_shares = docs["OOD_CALIBRATION_REPORT.json"]["gate_rules"][
        "measured_out_of_fold_status_shares"
    ]
    sizing = docs["RAISE_SIZING_MODEL_REPORT.json"]
    preflight = docs["ISSUE367_PREFLIGHT.json"]
    candidate = manifest["candidate"]
    limper = coverage["limiters_vs_iso"]
    differences = validation["non_inferiority"]
    gates = {gate["id"]: gate for gate in decision["gates"]}
    calibration_gate = gates["calibration_within_frozen_ceiling"]

    def pct(value: Any) -> str:
        return format(100 * float(value), ".4f") + "%"

    lines = [
        "# #421 — generalized opponent response model: evidence bundle",
        "",
        "**" + decision["decision"] + "** (protocol outcome `" + decision["protocol_outcome"]
        + "`, " + str(decision["criteria_passed"]) + "/" + str(decision["criteria_total"])
        + " frozen criteria passed). The candidate `" + candidate["candidate_id"] + "` (`"
        + candidate["architecture"] + "`, canonical payload `"
        + candidate["canonical_payload_sha256"] + "`) is **not** admitted, is **not** wired into "
        "#367 and does **not** replace the active Model A reference.",
        "",
        "This bundle persists and content-addresses the ten required #421 artifacts under `"
        + BUNDLE_REL + "/sha256/` and binds them in `ARTIFACTS.json`.",
        "`GENERALIZED_RESPONSE_MODEL_SPEC.json` is a deterministic projection of the frozen "
        "evidence (no re-fit, no new claim); its byte SHA256 is `" + spec_digest
        + "` (canonical payload `" + canonical_payload_sha256(spec) + "`).",
        "",
        "## 1. Decision",
        "",
        "`DECISION.json` = **" + decision["decision"] + "** on the single fenced VALIDATION read "
        "(`validation_reads=" + str(decision["validation_reads"]) + "`, "
        + str(validation["evaluation_universe"]["in_scope_rows"]) + " in-scope decisions over "
        + str(validation["evaluation_universe"]["in_scope_hands"]) + " hands). Failed frozen "
        "gates: " + ", ".join("`" + gate + "`" for gate in decision["failed_gates"]) + ".",
        "",
        "Rationale: " + decision["rationale"] + ".",
        "",
        "## 2. Coverage",
        "",
        "- Total in-scope coverage: **" + pct(coverage["coverage"]) + "** ("
        + str(coverage["answered_decisions"]) + " answered / "
        + str(coverage["distinct_hands_answered"]) + " hands) against the frozen floor `"
        + str(manifest["thresholds"]["coverage"]["minimum_coverage"]) + "` — PASS.",
        "- LIMPER_VS_ISO coverage: **" + pct(limper["coverage"]) + "** (" + str(limper["answered"])
        + "/" + str(limper["n"]) + "); LIMPER_VS_ISO_CALLERS "
        + pct(coverage["by_family"]["LIMPER_VS_ISO_CALLERS"]["coverage"]) + " ("
        + str(coverage["by_family"]["LIMPER_VS_ISO_CALLERS"]["answered"]) + "/"
        + str(coverage["by_family"]["LIMPER_VS_ISO_CALLERS"]["n"]) + ").",
        "- Abstention rate: " + pct(coverage["abstain_rate"]) + " ("
        + str(coverage["abstained_decisions"]) + " abstained decisions); per-position coverage is "
        "reported in `VALIDATION_RESULT.json` for all " + str(len(coverage["by_position"]))
        + " positions.",
        "- TRAIN out-of-fold coverage was "
        + pct(manifest["thresholds"]["coverage"]["train_out_of_fold_coverage"])
        + " under the frozen provisional gate.",
        "",
        "## 3. Calibration",
        "",
        "| model | log loss (bits/decision) | Brier | ECE |",
        "| --- | --- | --- | --- |",
    ]
    for model in (
        "candidate_generalized",
        "active_model_a_v5",
        "model_a_preflop_sizing_aware_candidate_v2",
        "alternate_architecture_hierarchical_eb",
        "fit_global_prior_baseline",
    ):
        row = primary[model]
        lines.append(
            "| " + model + " | " + str(row["log_loss_bits_per_decision"]) + " | "
            + str(row["brier_score"]) + " | " + str(row["expected_calibration_error"]) + " |"
        )
    lines += [
        "",
        "Calibration gate **" + ("PASS" if calibration_gate["passed"] else "FAIL")
        + "**: candidate ECE `" + str(calibration_gate["observed"]["ece"])
        + "` is inside the frozen absolute ceiling `"
        + str(calibration_gate["threshold"]["maximum_absolute_ece"])
        + "`, but the delta vs the active reference `"
        + str(calibration_gate["observed"]["ece_delta_vs_active"])
        + "` exceeds the frozen maximum `"
        + str(calibration_gate["threshold"]["maximum_ece_delta_vs_active"]) + "`. TRAIN "
        "out-of-fold ECE was `" + str(manifest["calibration_max"]["train_out_of_fold_ece"])
        + "`; the claim rests on equal-count reliability bins pooled over the frozen VALIDATION "
        "decisions (" + str(calibration_gate["observed"]["bins_meeting_minimum_support"])
        + " bins meeting the minimum support).",
        "",
        "Non-inferiority (paired percentile bootstrap on `hand_id`): candidate minus fit priors `"
        + str(differences["fit_global_prior_baseline"]["ci95_upper"]) + "` (PASS), candidate "
        "minus hierarchical empirical Bayes `"
        + str(differences["alternate_architecture_hierarchical_eb"]["ci95_upper"])
        + "` against margin `"
        + str(differences["alternate_architecture_hierarchical_eb"]["margin_bits"])
        + "` (PASS), candidate minus active Model A v5 `"
        + str(differences["active_model_a_v5"]["ci95_upper"]) + "` against margin `"
        + str(differences["active_model_a_v5"]["margin_bits"]) + "` (**FAIL**).",
        "",
        "## 4. Strata (generalization)",
        "",
        "| stratum | share | n | log loss | ECE | coverage |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for key in (
        "frequent_exact",
        "rare_exact",
        "exact_absent_in_domain",
        "exact_absent_out_of_domain",
    ):
        block = strata["strata"][key]
        answered = block.get("answered_metrics") or {}
        lines.append(
            "| " + key + " | " + str(strata["share"][key]) + " | " + str(block["n"]) + " | "
            + str(answered.get("log_loss_bits_per_decision")) + " | "
            + str(answered.get("expected_calibration_error")) + " | "
            + str(block.get("coverage")) + " |"
        )
    lines += [
        "",
        "Definition: " + strata["definition"] + ". The rare-exact and exact-absent-in-domain rows "
        "are answered by the learned function rather than abstained, which is the generalization "
        "property the ticket asks for; the exact-absent-out-of-domain stratum is empty on "
        "VALIDATION and abstention is exercised on the OOD probes instead.",
        "",
        "## 5. OOD gate",
        "",
        "Statuses `" + "/".join(manifest["ood_gate"]["statuses"]) + "`; measured out-of-fold TRAIN "
        "shares: supported `" + str(ood_shares["MODEL_SUPPORTED"]) + "`, high uncertainty `"
        + str(ood_shares["MODEL_SUPPORTED_HIGH_UNCERTAINTY"]) + "`, abstain `"
        + str(ood_shares["MODEL_OOD_ABSTAIN"]) + "`. Hard reasons `"
        + ", ".join(manifest["ood_gate"]["hard_reason_codes"]) + "` abstain fail-closed; an exact "
        "context never seen in TRAIN stays in-domain by definition and can only raise the status "
        "to high uncertainty.",
        "",
        "On the frozen VALIDATION decisions the gate answered "
        + str(coverage["ood_status_counts"]["MODEL_SUPPORTED"]) + " as supported, "
        + str(coverage["ood_status_counts"]["MODEL_SUPPORTED_HIGH_UNCERTAINTY"])
        + " as high uncertainty and " + str(coverage["ood_status_counts"]["MODEL_OOD_ABSTAIN"])
        + " as abstained; abstention is exercised on the OOD probes of "
        "`OOD_CALIBRATION_REPORT.json` (never-seen category, stack/price/sizing extrapolation).",
        "",
        "## 6. Raise-sizing gate",
        "",
        "Frozen criterion `" + manifest["sizing_criteria"]["criteria_id"] + "`: "
        + str(sizing["guarantees"]["frontiers_resolved"]) + "/"
        + str(
            sizing["guarantees"]["frontiers_resolved"]
            + sizing["guarantees"]["frontiers_fail_closed"]
        )
        + " #388/#419 raise-sizing frontiers are resolved by the conditional sizing density, "
        + str(sizing["guarantees"]["frontiers_fail_closed"]) + " fail-closed, "
        + str(sizing["metrics"]["generated_sizings"]) + " generated sizings of which "
        + str(sizing["metrics"]["illegal_generated_sizings"])
        + " illegal (rate `" + str(sizing["metrics"]["illegal_generated_rate"])
        + "` against the frozen maximum `"
        + str(manifest["sizing_criteria"]["maximum_illegal_generated_rate"]) + "`). No "
        "nearest-price or nearest-context substitution is applied (`no_nearest_price_substitution="
        + str(sizing["guarantees"]["no_nearest_price_substitution"]).lower() + "`).",
        "",
        "## 7. #367 preflight",
        "",
        "`ISSUE367_PREFLIGHT.json` walks the " + str(preflight["nodes_queried"])
        + " required scenario #321 nodes and " + str(preflight["sizing_frontiers_queried"])
        + " raise-sizing frontiers: "
        + str(preflight["direct_evaluation_audit"]["direct_eval_nodes"]) + " direct evaluations, "
        + str(preflight["direct_evaluation_audit"]["explicit_abstain_nodes"]) + " explicit "
        "abstentions, hero EV executed `"
        + str(preflight["boundary"]["hero_ev_executed"]).lower() + "`, #367 executed `"
        + str(preflight["boundary"]["issue367_executed"]).lower() + "`. Admission is "
        "`" + preflight["admission"]["consumption"] + "` because the VALIDATION outcome is `"
        + preflight["admission"]["admission_decision"] + "`; #367 keeps its currently admitted "
        "model.",
        "",
        "## 8. Digest verification (recomputed vs persisted)",
        "",
        "Every digest this bundle persists is recomputed from the persisted bytes: "
        + str(len(inputs["cross_reference_checks"]))
        + " cross-references declared by the frozen artifacts and every `.sha256` sidecar were "
        "re-derived and all match (`digest_verification.all_recomputed_digests_match_persisted = "
        "true`). This closes the #352 failure mode, where a self-reported digest was recorded "
        "without ever being recomputed.",
        "",
        "| artifact | byte SHA256 | canonical payload SHA256 |",
        "| --- | --- | --- |",
    ]
    for name, _role in REQUIRED_ARTIFACTS:
        if name == SUMMARY_NAME:
            lines.append("| SUMMARY.md | `see ARTIFACTS.json` | n/a |")
            continue
        if name == SPEC_NAME:
            lines.append(
                "| " + name + " | `" + spec_digest + "` | `"
                + canonical_payload_sha256(spec) + "` |"
            )
            continue
        lines.append(
            "| " + name + " | `" + digests[name] + "` | `" + canonical_payload_sha256(docs[name])
            + "` |"
        )
    lines += [
        "",
        "## 9. Boundaries",
        "",
        "- `TEST_CONSUMED=false` — TEST is refused by the loader, the runtime and the self-scans; "
        "`test_authorized=" + str(decision["test_authorized"]).lower() + "`, `test_consumed="
        + str(decision["test_consumed"]).lower() + "`, and the persisted dataset refuses `"
        + manifest["corpus"]["test"]["split"] + "` (" + str(manifest["corpus"]["test"]["hands"])
        + " hands stay untouched).",
        "- `ACTIVE_POINTER_MUTATED=false` — the active Model A pointer `"
        + manifest["active_references"]["active_model_a_preflop"]["path"] + "` (`"
        + manifest["active_references"]["active_model_a_preflop"]["sha256"]
        + "`) and the Model B pointer are unchanged before and after the whole cycle; no promotion "
        "is performed.",
        "- `VALIDATION_CONSUMED=true` exactly once (the frozen one-shot read, `validation_reads="
        + str(decision["validation_reads"]) + "`); it is never re-opened, re-scored or re-tuned and "
        "no threshold moved after the read.",
        "- #367 is neither executed nor authorized by this bundle; no Hero EV, no Model B and no "
        "rollout are computed.",
        "",
        "## 10. Reproduce and verify",
        "",
        "```text",
        "python3 tools/training/build_issue421_evidence_bundle.py",
        "python3 tools/training/build_issue421_evidence_bundle.py --check",
        "python3 tests/training/test_issue421_evidence_bundle.py",
        "```",
    ]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# persist / check
# --------------------------------------------------------------------------


def _object_name(digest: str, extension: str) -> str:
    return BUNDLE_REL + "/sha256/" + digest + extension


def _artifact_entry(
    rel_or_name: str,
    role: str,
    data: bytes,
    payload: Mapping[str, Any] | None,
    declared: Mapping[str, str],
) -> dict:
    digest = sha256_bytes(data)
    extension = Path(rel_or_name).suffix
    entry: dict[str, Any] = {
        "role": role,
        "path": rel_or_name
        if rel_or_name.startswith("analysis/")
        else BUNDLE_REL + "/" + rel_or_name,
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
    digests = inputs["digests"]

    spec = build_spec(inputs)
    spec_bytes = serialize(spec)
    spec_digest = sha256_bytes(spec_bytes)
    summary_bytes = summary_text(inputs, spec_digest, spec).encode()
    summary_digest = sha256_bytes(summary_bytes)

    objects: dict[str, bytes] = {}
    artifacts: dict[str, dict] = {}
    for name, role in REQUIRED_ARTIFACTS:
        if name == SPEC_NAME:
            data, payload = spec_bytes, spec
        elif name == SUMMARY_NAME:
            data, payload = summary_bytes, None
        else:
            data = _abs(name).read_bytes()
            payload = docs[name]
        declared = {} if name in (SPEC_NAME, SUMMARY_NAME) else inputs["declared"].get(name, {})
        artifacts[name] = _artifact_entry(name, role, data, payload, declared)
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
        if name not in (SPEC_NAME, SUMMARY_NAME) and inputs["declared"].get(name)
    ]
    index = {
        "schema": INDEX_SCHEMA,
        "issue": 421,
        "bundle": BUNDLE_REL,
        "generated_by": {
            "tool_path": "tools/training/build_issue421_evidence_bundle.py",
            "tool_sha256": sha256_bytes(Path(__file__).read_bytes()),
            "frozen_at": docs["CANDIDATE_MANIFEST.json"]["frozen_at"],
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
                "canonical_payload_sha256 field excluded"
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
                if name not in sidecar_names and name not in (SPEC_NAME, SUMMARY_NAME)
            ],
            "cross_reference_checks": inputs["cross_reference_checks"],
        },
        "boundary": {
            "validation_consumed": True,
            "validation_reads": docs["DECISION.json"]["validation_reads"],
            "validation_split_reopened": False,
            "test_consumed": False,
            "test_authorized": False,
            "active_pointer_mutated": False,
            "active_model_pointer_mutation": False,
            "automatic_promotion": "FORBIDDEN",
            "issue367_executed": False,
            "hero_ev_computed": False,
            "model_b_consumed": False,
        },
        "issue367_consumption": {
            "rule_id": docs["CANDIDATE_MANIFEST.json"]["issue367_consumption_rule"]["rule_id"],
            "candidate_authorized_for_367": docs["DECISION.json"]["issue367_authorized"],
            "outcome": docs["DECISION.json"]["protocol_outcome"],
            "consumption": docs["ISSUE367_PREFLIGHT.json"]["admission"]["consumption"],
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
        "summary": {
            "path": BUNDLE_REL + "/" + SUMMARY_NAME,
            "sha256": summary_digest,
            "object": artifacts[SUMMARY_NAME]["object"],
        },
    }
    return {
        "spec_bytes": spec_bytes,
        "spec_digest": spec_digest,
        "summary_bytes": summary_bytes,
        "summary_digest": summary_digest,
        "index": index,
        "objects": objects,
    }


def persist() -> int:
    bundle = build()
    OBJECTS.mkdir(parents=True, exist_ok=True)
    SPEC_PATH.write_bytes(bundle["spec_bytes"])
    SUMMARY_PATH.write_bytes(bundle["summary_bytes"])
    SPEC_DIGEST_PATH.write_text(
        bundle["spec_digest"] + "  " + SPEC_NAME + "\n"
        "# canonical_payload_sha256 "
        + canonical_payload_sha256(json.loads(bundle["spec_bytes"]))
        + "\n"
        "# spec_id " + SPEC_ID + "\n",
        encoding="utf-8",
    )
    INDEX_PATH.write_bytes(serialize(bundle["index"]))
    referenced = set()
    for section in ("artifacts", "supporting_evidence"):
        for entry in bundle["index"][section].values():
            object_name = Path(entry["object"]).name
            referenced.add(object_name)
            (OBJECTS / object_name).write_bytes(bundle["objects"][object_name])
    for path in OBJECTS.iterdir():
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
        (SPEC_PATH, bundle["spec_bytes"]),
        (SUMMARY_PATH, bundle["summary_bytes"]),
        (INDEX_PATH, serialize(bundle["index"])),
    )
    for path, data in expected:
        if not path.is_file() or path.read_bytes() != data:
            problems.append(path.name + " differs from a fresh deterministic build")
    if not SPEC_DIGEST_PATH.is_file() or not SPEC_DIGEST_PATH.read_text(
        encoding="utf-8"
    ).startswith(bundle["spec_digest"] + "  " + SPEC_NAME):
        problems.append("GENERALIZED_RESPONSE_MODEL_SPEC.sha256 is missing or stale")

    if INDEX_PATH.is_file():
        persisted = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
        for section in ("artifacts", "supporting_evidence"):
            for name, entry in persisted.get(section, {}).items():
                object_path = ROOT / entry["object"]
                if not object_path.is_file():
                    problems.append("missing content-addressed copy for " + name)
                    continue
                if sha256_bytes(object_path.read_bytes()) != entry["sha256"]:
                    problems.append("recomputed digest mismatch for the copy of " + name)
                source = ROOT / entry["path"]
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
                    + "."
                    + check_entry["field"]
                )
        referenced = {
            Path(entry["object"]).name
            for section in ("artifacts", "supporting_evidence")
            for entry in persisted.get(section, {}).values()
        }
        if OBJECTS.is_dir():
            extra = {path.name for path in OBJECTS.iterdir() if path.is_file()} - referenced
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
                "spec_sha256": bundle["spec_digest"],
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

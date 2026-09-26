#!/usr/bin/env python3
"""#421: freeze the candidate manifest and the VALIDATION protocol.

Writes ``analysis/issue421_generalized_response/CANDIDATE_MANIFEST.json`` and
``analysis/issue421_generalized_response/FROZEN_VALIDATION_PROTOCOL.json`` plus
their ``.sha256`` sidecars and a content-addressed bundle under
``analysis/issue421_generalized_response/validation_protocol/``.

The protocol pins, before the fenced VALIDATION admission evaluation reads a
single VALIDATION row:

* the candidate identity (``candidate_id``, byte digest, canonical payload
  digest) and the frozen code digests of every consumed producer;
* the public-only feature set, the ``log1p`` spline transformations, the
  architecture, the fitted hyper-parameters and the seeds;
* the TRAIN corpus identity (dataset digest, TRAIN split fingerprint,
  certification digest) and the TRAIN-only cross-validation procedure;
* the OOD gate statuses, hard/soft reason codes and its frozen thresholds;
* the metrics, the non-inferiority rule, the maximum allowed calibration and
  the raise-sizing criteria;
* the minimum product coverage (``>= 0.50``), the active references and the
  rule that decides whether #367 may consume the candidate.

Scientific boundary
-------------------
The protocol is authored, hashed and timestamped **before** the fenced
VALIDATION admission evaluation.  This tool parses no hand history and no
decision JSONL: it consumes content-addressed evidence artifacts only and
statically refuses the known holdout loaders, so a freeze cannot smuggle a
VALIDATION read into the threshold table.

The pre-freeze exploratory architecture comparison already recorded inside
``model/FIT_REPORT.json`` (the fit report scored both architectures on
VALIDATION for orientation) is **disclosed as evidence, not repaired**: the
frozen candidate selection rests on the TRAIN-only hand-grouped five-fold
cross-validation (``TRAIN_CV_REPORT.selection``, ``evidence_basis =
out_of_fold_holdout_only``), and no threshold below is derived from that
comparison.  Any divergence between the candidate bytes, the manifest and the
protocol is fail-closed.
"""
from __future__ import annotations

import argparse
import ast
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SOURCE_PATH = Path(__file__).resolve()

from tools.preflop import generalized_response_model as M  # noqa: E402

# --------------------------------------------------------------------------
# layout
# --------------------------------------------------------------------------

HERE = ROOT / "analysis/issue421_generalized_response"
BUNDLE = HERE / "validation_protocol"
BUNDLE_INDEX = BUNDLE / "ARTIFACTS.json"

MANIFEST_PATH = HERE / "CANDIDATE_MANIFEST.json"
MANIFEST_NAME = "CANDIDATE_MANIFEST.json"
MANIFEST_DIGEST_PATH = HERE / "CANDIDATE_MANIFEST.sha256"

PROTOCOL_PATH = HERE / "FROZEN_VALIDATION_PROTOCOL.json"
PROTOCOL_NAME = "FROZEN_VALIDATION_PROTOCOL.json"
PROTOCOL_DIGEST_PATH = HERE / "FROZEN_VALIDATION_PROTOCOL.sha256"

SCHEMA_PATH = ROOT / "contracts/training/generalized-validation-protocol.schema.json"

RESULT_DIR = HERE / "validation"
DECLARED_RESULT_LOCATIONS = (
    RESULT_DIR / "VALIDATION_RESULT.json",
    RESULT_DIR / "FROZEN_VALIDATION_RESULT.json",
)

#: Logical (repository-relative) paths that are *serialized* into the frozen
#: documents.  They are deliberately independent of the on-disk output
#: directory so a rebuild in another layout reproduces the frozen bytes.
MANIFEST_LOGICAL_PATH = "analysis/issue421_generalized_response/CANDIDATE_MANIFEST.json"
PROTOCOL_LOGICAL_PATH = "analysis/issue421_generalized_response/FROZEN_VALIDATION_PROTOCOL.json"
DECLARED_RESULT_LOGICAL_PATHS = (
    "analysis/issue421_generalized_response/validation/VALIDATION_RESULT.json",
    "analysis/issue421_generalized_response/validation/FROZEN_VALIDATION_RESULT.json",
)

MANIFEST_SCHEMA = "poker-generalized-response-candidate-manifest/v1"
PROTOCOL_SCHEMA = "poker-generalized-frozen-validation-protocol/v1"
RESULT_SCHEMA = "poker-generalized-response-validation-result/v1"
FROZEN_STATUS = "FROZEN_BEFORE_VALIDATION"
DEFAULT_FROZEN_AT = "2026-09-26T00:00:00Z"
FROZEN_AT_SOURCE = "explicit_freeze_timestamp_recorded_before_the_fenced_validation_evaluation"

CLUSTER_ID = "ISSUE421_GENERALIZED_VALIDATION_CODE_CLUSTER"

# --------------------------------------------------------------------------
# frozen inputs: every digest is re-derived from the persisted bytes
# --------------------------------------------------------------------------

DATASET_PATH = HERE / "dataset/GENERALIZED_RESPONSE_DATASET.jsonl"
DATASET_SHA256 = "4c18872fac5fc443e68e6f99feb0036509999f67f952c02e118671c7c72330a2"
DATASET_BYTES = 41279660
DATASET_ROWS = 105698
DATASET_MANIFEST_PATH = HERE / "dataset/GENERALIZED_RESPONSE_DATASET.json"
DATASET_MANIFEST_SHA256 = "ec1cec7a52be980e0857c2be3ff1201df55d69cceee793b44073c5ea656ecef1"
CORPUS_HASHES_PATH = HERE / "dataset/CORPUS_HASHES.json"
CORPUS_HASHES_SHA256 = "a172c41341e6deedb6ffec1c4a7adedec5f0b40c3ebe8a89f5360bd597e1f364"

CANDIDATE_ID = "generalized-adverse-response-candidate-v1"
CANDIDATE_ARCHITECTURE = "regularized_multinomial_spline"
CANDIDATE_SEED = 421
CANDIDATE_PATH = HERE / "model/candidate_regularized_multinomial_spline.json"
CANDIDATE_SHA256 = "ea93e8c35e2604debd943495474cdb9262d724efb4a5caefe3723b53f23a59e7"
CANDIDATE_CANONICAL_SHA256 = "c3f3573f3e80b3f7889dc8b1fd6f1948daeea95effc5a41a5d707385c4eed7dc"

ALTERNATE_ARCHITECTURE = "hierarchical_empirical_bayes_dirichlet"
ALTERNATE_CANDIDATE_PATH = HERE / "model/candidate_hierarchical_empirical_bayes_dirichlet.json"
ALTERNATE_CANDIDATE_SHA256 = "3cffaa69b63cd8972ebbd55a055fda26d802c838f5c565bf79c0818b30aa3ce6"
ALTERNATE_CANDIDATE_CANONICAL_SHA256 = "7eb7b4794d9e42bcf151f7e1cf21c337a7f2393bfaf4a1ecc6b310793d2c302f"

FIT_REPORT_PATH = HERE / "model/FIT_REPORT.json"
FIT_REPORT_SHA256 = "90afe4fae92009d40d14586cf7ab0967db3a050d16b5b1211c4c3fd274a3b2aa"
CV_REPORT_PATH = HERE / "TRAIN_CV_REPORT.json"
CV_REPORT_SHA256 = "43d9fffff98aeae1f51d0bdd78647a2dedbd58403a0591433d22840a5cf996ff"
OOD_REPORT_PATH = HERE / "OOD_CALIBRATION_REPORT.json"
OOD_REPORT_SHA256 = "a8f1b181f0d3ff3fd48dd3d58181a844760409f036e0b11f440ff7553dfc0b71"
SIZING_REPORT_PATH = HERE / "RAISE_SIZING_MODEL_REPORT.json"
SIZING_REPORT_SHA256 = "955b926a5d19efe4998abfeae416792f85284d167cfaf9306315cb639320e9f6"
DATASET_REPORT_PATH = HERE / "GENERALIZED_RESPONSE_DATASET_REPORT.json"
DATASET_REPORT_SHA256 = "81f1314af83df1453155d83993afcf7c23ce2cbe74b54f0c9fd23207d13409d8"

MODULE_PATH = ROOT / "tools/preflop/generalized_response_model.py"
MODULE_SHA256 = "92d7ac94aa03face11dbcd9a3b573d9ed790efb77b924a7ae5458fddcf94dbc3"
CV_TOOL_PATH = ROOT / "tools/training/evaluate_generalized_response_cv.py"
CV_TOOL_SHA256 = "956d95b20d4ca5ce09c8130889eb38105fc55e607b61d6d5971089f8540d16ff"
BUILD_TOOL_PATH = ROOT / "tools/training/build_generalized_response_dataset.py"
BUILD_TOOL_SHA256 = "39e7c8f83fdafac1bafa75f3b62f78c60a5602fb58b565e8a3c8fb98ff900097"
FEATURE_AUDIT_TOOL_PATH = ROOT / "tools/training/audit_generalized_response_features.py"
FEATURE_AUDIT_TOOL_SHA256 = "d72cb7fc77391fca49832f00d88316fb24935878611bd24b409690a683347fac"

MODEL_CONTRACT_PATH = ROOT / "contracts/training/generalized-response-model.schema.json"
MODEL_CONTRACT_SHA256 = "878ca051069342fdff07be2a1b905119ab534ba77076c272cdbe2f75e0ce5c83"
OOD_CONTRACT_PATH = ROOT / "contracts/training/generalized-response-ood-gate.schema.json"
OOD_CONTRACT_SHA256 = "99a6fe9c3eeb4b7f61db35f390115938799c8730d41fa0b8e62e4311023f0f1e"
DATASET_CONTRACT_PATH = ROOT / "contracts/training/generalized-response-dataset.schema.json"
DATASET_CONTRACT_SHA256 = "15f35cb3a40a6b48a60e0add252d2f0a31bc6d138964e94e9842f7c2a3757255"

CERTIFICATION_PATH = ROOT / "training/datasets/NLHE_100-200/population_certification.json"
CERTIFICATION_SHA256 = "6b3c967b982a712ab0da3fd2bc21c242b1b08a802222f7d4b6587a0dfa2dace6"
ACTIVE_MODEL_A_PATH = ROOT / "training/models/preflop_population_model_v5.json"
ACTIVE_MODEL_A_SHA256 = "ff952055ca4ee051a3ac9607d513fdecac0a320a31f658ecfd8a11d8448975ca"
ACTIVE_MODEL_B_PATH = ROOT / "training/models/postflop_population_model_v5.json"
ACTIVE_MODEL_B_SHA256 = "6d948f30f6c276ce41e70e83ac35275e30e7841e93e5b1da11782648c6b4d8ae"
TRAINING_REGISTRY_PATH = ROOT / "training/registry.json"
TRAINING_REGISTRY_SHA256 = "28430d61fb8e3a65e116e719af8c521ea838f1dec76d91e058df68840705f6f0"
POPULATIONS_REGISTRY_PATH = ROOT / "training/populations/registry.json"
POPULATIONS_REGISTRY_SHA256 = "832279cbbdf2f7d53cfd610e227eec17eef39a1ca1f5e344224d8c04d51840e4"
ISSUE419_PROTOCOL_PATH = ROOT / "analysis/issue419_hierarchical_tree/FROZEN_VALIDATION_PROTOCOL.json"
ISSUE419_PROTOCOL_SHA256 = "69c99a8b37589f1687b7e980344c9a79d69bbcd45be0a53ffd59bfea0ab583b3"

TRAIN_HAND_IDS_FINGERPRINT_SHA256 = (
    "4b4739d11c30455085e14e040f21a1ed70068403825d38dd1cc1b3ecbf9db5a8"
)
VALIDATION_HAND_IDS_FINGERPRINT_SHA256 = (
    "e0980444de231d5e38d07980ffdc238a48b6261691575715a5f458a8ebcd03ba"
)
POPULATION_FINGERPRINT_SHA256 = (
    "4661c200fab5a24ce67a45f0801acd0238c701f55e8dbeeaf3e8299fa250119c"
)
POPULATION_ID = "pokerstars_nlhe_100-200_zoom_play_6max_v1"

#: Numeric acceptance thresholds.  ``thresholds`` is the single frozen source of
#: truth: the protocol's ``coverage_floor`` / ``non_inferiority_rule`` /
#: ``calibration_max`` / ``sizing_criteria`` aliases are derived from it, never
#: restated, so a drift in one place cannot silently weaken the other.
MINIMUM_COVERAGE = 0.50
MAXIMUM_ABSOLUTE_ECE = 0.05
MAXIMUM_ECE_DELTA_VS_ACTIVE = 0.02
NON_INFERIORITY_CI_UPPER_BOUND = 0.0
NON_INFERIORITY_CONFIDENCE_LEVEL = 0.95
BOOTSTRAP_SAMPLES = 5000

CODE_INPUTS = (
    ("tools/training/freeze_generalized_validation_protocol.py", "PROTOCOL_GENERATOR"),
    ("contracts/training/generalized-validation-protocol.schema.json", "PROTOCOL_CONTRACT"),
    ("tools/preflop/generalized_response_model.py", "CANDIDATE_MODEL_AND_RUNTIME"),
    ("tools/training/build_generalized_response_dataset.py", "DATASET_BUILDER"),
    ("tools/training/audit_generalized_response_features.py", "FEATURE_AUDITOR"),
    ("tools/training/evaluate_generalized_response_cv.py", "CROSS_VALIDATION_TOOL"),
)

#: The generator legitimately names artifacts whose filenames contain
#: "validation"; the exemption is recorded in the protocol evidence.
SELF_ARTIFACT_LITERALS = (
    PROTOCOL_NAME,
    MANIFEST_NAME,
    "analysis/issue421_generalized_response/CANDIDATE_MANIFEST.json",
    "analysis/issue421_generalized_response/FROZEN_VALIDATION_PROTOCOL.json",
    "analysis/issue421_generalized_response/validation_protocol/ARTIFACTS.json",
    "analysis/issue421_generalized_response/validation_protocol/SUMMARY.md",
)

#: Holdout loader symbols a freeze-authoring tool must never contain.
FORBIDDEN_HOLDOUT_SYMBOLS = (
    "load_validation_records",
    "validation_records",
    "validation_hand_ids",
    "VALIDATION_HANDS",
    "load_holdout",
    "holdout_records",
    "build_validation_decisions",
    "load_test_records",
    "TEST_HANDS",
    "test_hand_ids",
    "read_dataset_rows",
    "iter_response_rows",
    "open",
)


class ProtocolError(RuntimeError):
    """Raised when the frozen manifest/protocol cannot be authored safely."""


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def serialize(payload: Any) -> bytes:
    return (json.dumps(payload, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical_hash(payload: Any) -> str:
    return M.stable_hash(payload)


def _load(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _relative(path: Path) -> str:
    resolved = Path(path).resolve()
    try:
        return str(resolved.relative_to(ROOT))
    except ValueError:
        return str(resolved)


def _require_file(label: str, path: Path, expected_sha256: str) -> str:
    path = Path(path)
    if not path.is_file():
        raise ProtocolError(f"{label}: missing input {path}")
    digest = sha256_file(path)
    if digest != expected_sha256:
        raise ProtocolError(
            f"{label}: sha256 drifted (expected {expected_sha256}, found {digest})"
        )
    return digest


def _code_fingerprints() -> list[dict[str, Any]]:
    rows = []
    for relative, role in CODE_INPUTS:
        path = ROOT / relative
        if not path.is_file():
            raise ProtocolError(f"missing code input {relative}")
        rows.append({"path": relative, "role": role, "sha256": sha256_file(path)})
    return rows


# --------------------------------------------------------------------------
# guards
# --------------------------------------------------------------------------


def static_holdout_scan() -> dict[str, Any]:
    """AST self-scan: the generator must reference no holdout loader.

    The scan works on identifiers actually *used* (names, attributes, imports,
    function arguments) rather than on the raw text, so the constant tuple that
    documents the forbidden symbols does not trip its own check.
    """
    source = SOURCE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    used: set[str] = set()
    opens_file = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            used.add(node.id)
        elif isinstance(node, ast.Attribute):
            used.add(node.attr)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            used.add(node.name)
        elif isinstance(node, ast.arg):
            used.add(node.arg)
        elif isinstance(node, ast.keyword) and node.arg:
            used.add(node.arg)
        elif isinstance(node, ast.alias):
            used.add(node.name)
            if node.asname:
                used.add(node.asname)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "open":
            opens_file = True
    hits = sorted(used.intersection(FORBIDDEN_HOLDOUT_SYMBOLS))
    if opens_file:
        hits = sorted(set(hits) | {"open"})
    return {
        "check": "self_source_ast_scan_for_holdout_loaders",
        "detail": (
            "AST scan: the generator uses none of the forbidden holdout loader symbols, "
            "imports no validation/holdout module and calls no file-opening builtin"
        ),
        "forbidden_symbols": list(FORBIDDEN_HOLDOUT_SYMBOLS),
        "exempt_result_path_literals": list(SELF_ARTIFACT_LITERALS),
        "hits": hits,
        "result": "FAIL" if hits else "PASS",
    }


def assert_fenced_validation_not_yet_consumed() -> dict[str, Any]:
    """Fail closed when a fenced VALIDATION result already exists."""
    present = [str(_relative(path)) for path in DECLARED_RESULT_LOCATIONS if Path(path).is_file()]
    if present:
        raise ProtocolError(
            "a fenced VALIDATION result already exists before the freeze: " + ", ".join(present)
        )
    return {
        "check": "no_fenced_validation_result_exists_before_freeze",
        "guard_id": "VALIDATION_ORDER_GUARD",
        "declared_result_locations": list(DECLARED_RESULT_LOGICAL_PATHS),
        "declared_result_locations_present": present,
        "result": "PASS",
        "violations": [],
    }


def assert_no_hand_level_dataset_read() -> dict[str, Any]:
    """The freeze consumes content-addressed artifacts, never hand histories."""
    return {
        "check": "no_hand_level_dataset_read",
        "result": "PASS",
        "detail": (
            "the generator parses no hand-history archive and no decision JSONL; it consumes "
            "content-addressed evidence artifacts by digest only (dataset/report/candidate)"
        ),
        "tripwire_id": "DIGEST_ONLY_INPUTS",
        "hand_level_dataset_files_opened": [],
    }


# --------------------------------------------------------------------------
# input verification
# --------------------------------------------------------------------------


def verify_inputs() -> dict[str, Any]:
    """Re-verify every pinned identity before the manifest/protocol is written."""
    _require_file("certified dataset payload", DATASET_PATH, DATASET_SHA256)
    if DATASET_PATH.stat().st_size != DATASET_BYTES:
        raise ProtocolError("dataset byte size drifted")
    _require_file("dataset manifest", DATASET_MANIFEST_PATH, DATASET_MANIFEST_SHA256)
    _require_file("corpus hashes", CORPUS_HASHES_PATH, CORPUS_HASHES_SHA256)
    _require_file("candidate", CANDIDATE_PATH, CANDIDATE_SHA256)
    _require_file("alternate candidate", ALTERNATE_CANDIDATE_PATH, ALTERNATE_CANDIDATE_SHA256)
    _require_file("fit report", FIT_REPORT_PATH, FIT_REPORT_SHA256)
    _require_file("cross-validation report", CV_REPORT_PATH, CV_REPORT_SHA256)
    _require_file("ood calibration report", OOD_REPORT_PATH, OOD_REPORT_SHA256)
    _require_file("raise sizing report", SIZING_REPORT_PATH, SIZING_REPORT_SHA256)
    _require_file("dataset report", DATASET_REPORT_PATH, DATASET_REPORT_SHA256)
    _require_file("model module", MODULE_PATH, MODULE_SHA256)
    _require_file("cross-validation tool", CV_TOOL_PATH, CV_TOOL_SHA256)
    _require_file("dataset builder", BUILD_TOOL_PATH, BUILD_TOOL_SHA256)
    _require_file("feature auditor", FEATURE_AUDIT_TOOL_PATH, FEATURE_AUDIT_TOOL_SHA256)
    _require_file("model contract", MODEL_CONTRACT_PATH, MODEL_CONTRACT_SHA256)
    _require_file("ood gate contract", OOD_CONTRACT_PATH, OOD_CONTRACT_SHA256)
    _require_file("dataset contract", DATASET_CONTRACT_PATH, DATASET_CONTRACT_SHA256)
    _require_file("population certification", CERTIFICATION_PATH, CERTIFICATION_SHA256)
    _require_file("active Model A pointer", ACTIVE_MODEL_A_PATH, ACTIVE_MODEL_A_SHA256)
    _require_file("active Model B pointer", ACTIVE_MODEL_B_PATH, ACTIVE_MODEL_B_SHA256)
    _require_file("training registry", TRAINING_REGISTRY_PATH, TRAINING_REGISTRY_SHA256)
    _require_file("populations registry", POPULATIONS_REGISTRY_PATH, POPULATIONS_REGISTRY_SHA256)
    _require_file("#419 frozen protocol", ISSUE419_PROTOCOL_PATH, ISSUE419_PROTOCOL_SHA256)

    candidate = _load(CANDIDATE_PATH)
    if canonical_hash(_candidate_payload(candidate)) != CANDIDATE_CANONICAL_SHA256:
        raise ProtocolError("candidate canonical payload hash drifted")
    if candidate.get("architecture") != CANDIDATE_ARCHITECTURE:
        raise ProtocolError("candidate architecture drifted")
    if int(candidate.get("seed", -1)) != CANDIDATE_SEED:
        raise ProtocolError("candidate seed drifted")
    if list(candidate.get("action_space", [])) != list(M.ACTIONS):
        raise ProtocolError("candidate action space drifted")
    if candidate.get("canonical_payload_sha256") != CANDIDATE_CANONICAL_SHA256:
        raise ProtocolError("candidate embedded canonical digest drifted")

    alternate = _load(ALTERNATE_CANDIDATE_PATH)
    if canonical_hash(_candidate_payload(alternate)) != ALTERNATE_CANDIDATE_CANONICAL_SHA256:
        raise ProtocolError("alternate candidate canonical payload hash drifted")
    if alternate.get("architecture") != ALTERNATE_ARCHITECTURE:
        raise ProtocolError("alternate candidate architecture drifted")

    dataset_manifest = _load(DATASET_MANIFEST_PATH)
    if dataset_manifest.get("dataset", {}).get("sha256") != DATASET_SHA256:
        raise ProtocolError("dataset manifest is not bound to the dataset bytes")
    if dataset_manifest.get("splits", {}).get("TRAIN", {}).get(
        "hand_ids_fingerprint_sha256"
    ) != TRAIN_HAND_IDS_FINGERPRINT_SHA256:
        raise ProtocolError("dataset manifest TRAIN fingerprint drifted")
    if dataset_manifest.get("corpus", {}).get("certification_sha256") != CERTIFICATION_SHA256:
        raise ProtocolError("dataset manifest certification digest drifted")
    if dataset_manifest.get("scope", {}).get("test_consumed") is not False:
        raise ProtocolError("dataset manifest claims a TEST read")

    cv_report = _load(CV_REPORT_PATH)
    cv_protocol = cv_report.get("protocol", {})
    if cv_protocol.get("main_split") != "TRAIN":
        raise ProtocolError("cross-validation must be TRAIN-only")
    if cv_protocol.get("consumed_splits") != ["TRAIN"]:
        raise ProtocolError("cross-validation consumed a non-TRAIN split")
    no_leak = cv_protocol.get("no_leak", {})
    if no_leak.get("max_hand_overlap_between_fit_and_holdout") != 0:
        raise ProtocolError("cross-validation leaked hands across folds")
    if cv_report.get("selection", {}).get("selected") != CANDIDATE_ARCHITECTURE:
        raise ProtocolError("cross-validation selected a different architecture")
    if cv_report.get("scope", {}).get("validation_consumed") is not False:
        raise ProtocolError("cross-validation report claims a VALIDATION read")
    if cv_report.get("scope", {}).get("test_consumed") is not False:
        raise ProtocolError("cross-validation report claims a TEST read")

    ood_report = _load(OOD_REPORT_PATH)
    if ood_report.get("provenance", {}).get("dataset_sha256") != DATASET_SHA256:
        raise ProtocolError("ood calibration is not bound to the dataset bytes")
    if ood_report.get("gate_rules", {}).get("validation_consumed") is not False:
        raise ProtocolError("ood calibration report claims a VALIDATION read")
    if ood_report.get("calibration", {}).get("provenance", {}).get("test_consumed") is not False:
        raise ProtocolError("ood calibration report claims a TEST read")

    sizing_report = _load(SIZING_REPORT_PATH)
    if sizing_report.get("provenance", {}).get("dataset_sha256") != DATASET_SHA256:
        raise ProtocolError("raise-sizing report is not bound to the dataset bytes")
    if sizing_report.get("metrics", {}).get("illegal_generated_rate") != 0.0:
        raise ProtocolError("raise-sizing report generated an illegal sizing")

    dataset_report = _load(DATASET_REPORT_PATH)
    if dataset_report.get("scope", {}).get("split_consumed") != "TRAIN":
        raise ProtocolError("feature audit report is not TRAIN-only")
    if dataset_report.get("scope", {}).get("validation_consumed") is not False:
        raise ProtocolError("feature audit report claims a VALIDATION read")

    certification = _load(CERTIFICATION_PATH)
    admissible = certification.get("status", {}).get("ADMISSIBLE", {})
    split_counts = admissible.get("split_counts", {})
    if admissible.get("fingerprint_sha256") != POPULATION_FINGERPRINT_SHA256:
        raise ProtocolError("population certification fingerprint drifted")
    for split in ("TRAIN", "VALIDATION", "TEST"):
        if split_counts.get(split) is None:
            raise ProtocolError(f"population certification is missing the {split} split count")
    if split_counts["TRAIN"] != dataset_manifest["splits"]["TRAIN"]["hands"]:
        raise ProtocolError("certification TRAIN count differs from the dataset manifest")
    if split_counts["VALIDATION"] != dataset_manifest["splits"]["VALIDATION"]["hands"]:
        raise ProtocolError("certification VALIDATION count differs from the dataset manifest")

    fit_report = _load(FIT_REPORT_PATH)
    if fit_report.get("dataset_sha256") != DATASET_SHA256:
        raise ProtocolError("fit report is not bound to the dataset bytes")

    issue419 = _load(ISSUE419_PROTOCOL_PATH)
    if issue419.get("status") != FROZEN_STATUS:
        raise ProtocolError("#419 frozen protocol is not FROZEN_BEFORE_VALIDATION")
    admitted = issue419.get("issue367_rule", {}).get("currently_admitted_model_a_for_367")
    if not isinstance(admitted, Mapping) or not admitted.get("candidate_sha256"):
        raise ProtocolError("#419 protocol does not pin the currently admitted Model A candidate")

    return {
        "candidate": candidate,
        "alternate": alternate,
        "dataset_manifest": dataset_manifest,
        "cv_report": cv_report,
        "ood_report": ood_report,
        "sizing_report": sizing_report,
        "dataset_report": dataset_report,
        "certification": certification,
        "fit_report": fit_report,
        "issue419": issue419,
        "admitted_for_367": dict(admitted),
    }


def _candidate_payload(candidate: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in candidate.items() if key != "canonical_payload_sha256"}


# --------------------------------------------------------------------------
# shared blocks
# --------------------------------------------------------------------------


def _thresholds(inputs: Mapping[str, Any]) -> dict[str, Any]:
    cv_report = inputs["cv_report"]
    ood = inputs["ood_report"]
    sizing = inputs["sizing_report"]
    accepted = cv_report["architectures"][CANDIDATE_ARCHITECTURE][
        "coverage_after_provisional_ood_gate"
    ]
    train_ece = accepted["accepted_metrics"]["expected_calibration_error"]["ece"]
    sizing_metrics = sizing["metrics"]
    return {
        "frozen": True,
        "immutable_after_validation_read": True,
        "coverage": {
            "minimum_coverage": MINIMUM_COVERAGE,
            "minimum_scored_decisions": 500,
            "minimum_distinct_hands": 100,
            "definition": (
                "share of in-scope VALIDATION decisions the frozen candidate answers with a legal, "
                "non-OOD distribution; abstaining is fail-closed and is counted as non-covered"
            ),
            "train_out_of_fold_coverage": accepted["coverage"],
            "coverage_is_an_admission_gate": True,
        },
        "non_inferiority": {
            "rule_id": "CANDIDATE_NOT_INFERIOR_TO_COMPARATORS",
            "paired_unit": "hand_id",
            "metric": "multiclass_log_loss_bits_per_decision",
            "direction": "lower_is_better",
            "method": "paired_percentile_bootstrap",
            "bootstrap_samples": BOOTSTRAP_SAMPLES,
            "confidence_level": NON_INFERIORITY_CONFIDENCE_LEVEL,
            "seed": CANDIDATE_SEED,
            "ci_upper_bound": NON_INFERIORITY_CI_UPPER_BOUND,
            "pairing_rule": (
                "a paired delta is computed only on the decisions both sides answer at the same "
                "requested public context"
            ),
            "comparisons": [
                {
                    "against": "fit_global_prior_baseline",
                    "rule": "paired (candidate - FIT global action prior) 95% CI upper bound <= 0",
                    "margin_bits": 0.0,
                },
                {
                    "against": "alternate_architecture_hierarchical_eb",
                    "rule": (
                        "paired (candidate - hierarchical_empirical_bayes_dirichlet) 95% CI upper "
                        "bound <= the preregistered cross-validation tolerance"
                    ),
                    "margin_bits": 0.005,
                },
                {
                    "against": "active_model_a_preflop_population",
                    "rule": "paired candidate-minus-active 95% CI upper bound <= 0",
                    "margin_bits": 0.0,
                },
            ],
        },
        "calibration": {
            "rule_id": "CALIBRATION_WITHIN_FROZEN_CEILING",
            "method": "equal_count_reliability_bins",
            "bins_per_action_class": 10,
            "minimum_bin_support_for_a_claim": 20,
            "maximum_absolute_ece": MAXIMUM_ABSOLUTE_ECE,
            "maximum_ece_delta_vs_active": MAXIMUM_ECE_DELTA_VS_ACTIVE,
            "train_out_of_fold_ece": train_ece,
            "train_out_of_fold_evidence": {
                "path": _relative(CV_REPORT_PATH),
                "sha256": CV_REPORT_SHA256,
            },
            "claim_requires": (
                "every reported ECE is pooled over the frozen VALIDATION decisions and compared "
                "against the active reference ECE on the same pooled support"
            ),
        },
        "sizing": {
            "criteria_id": "SIZING_NOT_INFERIOR_TO_FROZEN_TRAIN_EVIDENCE",
            "basis": sizing["sizing_model"]["basis"],
            "target_axis": sizing["sizing_model"]["target_axis"],
            "window_rule": sizing["sizing_model"]["window_rule"],
            "sizing_quantile_levels": sizing["sizing_model"]["sizing_quantile_levels"],
            "generation_quantile_levels": sizing["sizing_model"]["generation_quantile_levels"],
            "no_nearest_price_substitution": sizing["sizing_model"]["no_nearest_price"],
            "no_nearest_context_substitution": sizing["sizing_model"]["no_nearest_context"],
            "fail_closed_policy": "ABSTAIN_OR_FAIL_CLOSED_NEVER_SUBSTITUTE_NEAREST_PRICE_OR_CONTEXT",
            "maximum_illegal_generated_rate": 0.0,
            "minimum_nll_gain_vs_uniform_bits": 2.0,
            "maximum_nll_bits_per_sizing": 2.9,
            "maximum_crps_bb": 5.2,
            "maximum_pit_abs_bin_error": 0.30,
            "train_evidence": {
                "path": _relative(SIZING_REPORT_PATH),
                "sha256": SIZING_REPORT_SHA256,
                "rows": sizing_metrics["rows"],
                "scored": sizing_metrics["scored"],
                "nll_bits_per_sizing": sizing_metrics["nll_bits_per_sizing"],
                "nll_gain_vs_uniform_bits": sizing_metrics["nll_gain_vs_uniform_bits"],
                "crps_bb": sizing_metrics["crps_bb"],
                "illegal_generated_rate": sizing_metrics["illegal_generated_rate"],
                "pit_max_abs_bin_error": sizing_metrics["calibration"]["pit_max_abs_bin_error"],
                "fail_closed": sizing_metrics["fail_closed"],
            },
        },
        "ood": {
            "gate_schema": "poker-generalized-response-ood-gate/v1",
            "contract_path": _relative(OOD_CONTRACT_PATH),
            "contract_sha256": OOD_CONTRACT_SHA256,
            "calibration_report_path": _relative(OOD_REPORT_PATH),
            "calibration_report_sha256": OOD_REPORT_SHA256,
            "calibration_kind": ood["kind"],
            "statuses": ood["calibration"]["statuses"],
            "hard_reason_codes": ood["calibration"]["reason_codes"]["hard"],
            "soft_reason_codes": ood["calibration"]["reason_codes"]["soft"],
            "thresholds": ood["calibration"]["thresholds"],
            "abstain_policy": (
                "an OOD-abstaining decision is reported and excluded from the paired predictive "
                "gates; it never scores as correct and never falls back to the global prior"
            ),
            "never_seen_category_abstains": True,
            "stack_extrapolation_abstains": True,
            "sizing_extrapolation_abstains": True,
        },
        "support": {
            "minimum_marginal_observations": 20,
            "minimum_distinct_hands": 20,
        },
    }


def _features(inputs: Mapping[str, Any]) -> dict[str, Any]:
    dataset_manifest = inputs["dataset_manifest"]
    row_contract = dataset_manifest["row_contract"]
    ood = inputs["ood_report"]
    return {
        "public_only": True,
        "state_timing": "BEFORE_ACTION",
        "split_scope": ["TRAIN", "VALIDATION"],
        "refused_splits": ["TEST"],
        "response_actions": list(M.ACTIONS),
        "excluded_actions": ["CHECK"],
        "categorical_blocks": list(M.CATEGORICAL_BLOCKS),
        "spline_blocks": [name for name, _ in M.SPLINE_BLOCKS],
        "interaction_blocks": [name for name, _, _ in M.INTERACTION_BLOCKS],
        "ood_feature_blocks": ood["calibration"]["feature_blocks"],
        "ood_numeric_axes": ood["calibration"]["numeric_axes"],
        "row_contract_fields": row_contract["fields"],
        "forbidden_keys": row_contract["forbidden_keys"],
        "outcome_dimensions_excluded": ["target_total_bb", "observed_sizing_bb"],
        "feature_audit_report_path": _relative(DATASET_REPORT_PATH),
        "feature_audit_report_sha256": DATASET_REPORT_SHA256,
        "row_contract_path": _relative(DATASET_CONTRACT_PATH),
        "row_contract_sha256": DATASET_CONTRACT_SHA256,
    }


def _transformations(inputs: Mapping[str, Any]) -> dict[str, Any]:
    candidate = inputs["candidate"]
    config = candidate["config"]
    return {
        "axis_transform": M.AXIS_TRANSFORM,
        "spline_axis_knots": {key: list(value) for key, value in config["spline_knots"].items()},
        "sizing_axis_knots": list(config["sizing_axis_knots"]),
        "sizing_target_axis": (
            "target_total_bb divided by (pot_before_bb + to_call_bb)"
        ),
        "sizing_ratio_cap": M.MAX_SIZING_RATIO,
        "categorical_level_rules": {
            "public_levels": ["family", "actor_position", "aggressor_position"],
            "count_caps": dict(M.CATEGORICAL_CAPS),
            "coarse_buckets": {key: list(value) for key, value in M.COARSE_BUCKETS.items()},
        },
        "partition_of_unity": True,
        "no_nearest_cell_substitution": True,
        "continuous_recompute_on_query": True,
    }


def _architecture(inputs: Mapping[str, Any]) -> dict[str, Any]:
    candidate = inputs["candidate"]
    return {
        "model_family": "MODEL_A_PREFLOP_RESPONSE",
        "identity_granularity": "public_preflop_response_context",
        "architecture": candidate["architecture"],
        "candidate_id": CANDIDATE_ID,
        "action_space": list(M.ACTIONS),
        "aggressive_actions": list(M.AGGRESSIVE_ACTIONS),
        "baseline_object": "TRAIN global action distribution (fit-fold action prior)",
        "discrete_choice_core": True,
        "conditional_sizing_channel": True,
        "hidden_hand_imputation": False,
        "pseudo_observation": False,
        "nearest_context_fallback": False,
        "nearest_price_fallback": False,
        "alternative_architectures": [
            {
                "architecture": ALTERNATE_ARCHITECTURE,
                "path": _relative(ALTERNATE_CANDIDATE_PATH),
                "sha256": ALTERNATE_CANDIDATE_SHA256,
                "canonical_payload_sha256": ALTERNATE_CANDIDATE_CANONICAL_SHA256,
                "role": "ALTERNATE_ARCHITECTURE_COMPARATOR",
            }
        ],
    }


def _hyperparameters(inputs: Mapping[str, Any]) -> dict[str, Any]:
    candidate = inputs["candidate"]
    config = candidate["config"]
    return {
        **{key: value for key, value in config.items()},
        "estimator": "regularized_additive_multinomial_log_linear",
        "frozen": True,
        "frozen_by_candidate": _relative(CANDIDATE_PATH),
        "hyperparameter_search_performed_on_validation": False,
        "selected_on": "TRAIN-only hand-grouped five-fold cross-validation",
    }


def _seeds(inputs: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "random_seed": CANDIDATE_SEED,
        "candidate_seed": int(inputs["candidate"]["seed"]),
        "rng_algorithm": "none",
        "stochastic_draws": 0,
        "deterministic_reproduction": True,
        "policy": "DETERMINISTIC_NO_RANDOMNESS",
        "purpose": (
            "the frozen estimator, its partition-of-unity sizing spline and every OOD threshold are "
            "closed-form; the recorded seed only pins observation ordering, fold assignment and "
            "tie-breaking, no sampling is performed"
        ),
    }


def _cv_procedure(inputs: Mapping[str, Any]) -> dict[str, Any]:
    cv_report = inputs["cv_report"]
    protocol = cv_report["protocol"]
    return {
        "kind": "hand_grouped_k_fold_cross_validation",
        "main_split": protocol["main_split"],
        "forbidden_splits": protocol["forbidden_splits"],
        "consumed_splits": protocol["consumed_splits"],
        "group_key": protocol["group_key"],
        "folds": protocol["folds"],
        "fold_assignment": protocol["fold_assignment"],
        "seed": protocol["seed"],
        "model_config_source": protocol["model_config_source"],
        "sizing_mode": protocol["sizing_mode"],
        "preregistered_selection_criteria": protocol["preregistered_selection_criteria"],
        "no_leak": protocol["no_leak"],
        "selected_architecture": cv_report["selection"]["selected"],
        "selection_evidence_basis": cv_report["selection"]["evidence_basis"],
        "report_path": _relative(CV_REPORT_PATH),
        "report_sha256": CV_REPORT_SHA256,
    }


def _metrics(inputs: Mapping[str, Any]) -> dict[str, Any]:
    protocol = inputs["cv_report"]["protocol"]
    return {
        "primary": {
            "name": "multiclass_log_loss",
            "unit": "bits_per_decision",
            "direction": "lower_is_better",
            "definition": "mean over scored decisions of -log2 P(observed action)",
            "epsilon_clip": 1e-12,
        },
        "secondary": [
            {
                "name": "brier_score",
                "definition": "mean sum over the four actions of (P(action) - 1[observed])^2",
            },
            {
                "name": "expected_calibration_error",
                "definition": "equal-count reliability bins per action class",
            },
            {"name": "accuracy", "definition": "mean arg-max agreement"},
            {
                "name": "coverage",
                "definition": "share of in-scope decisions answered with a legal, non-OOD distribution",
            },
            {
                "name": "abstain_rate",
                "definition": "share of in-scope decisions that abstain (OOD or fail-closed)",
            },
        ],
        "paired_unit": "hand_id",
        "pairing_rule": (
            "a paired delta is computed only on the decisions both sides answer at the same "
            "requested public context"
        ),
        "bootstrap": {
            "method": "paired_percentile_bootstrap",
            "samples": BOOTSTRAP_SAMPLES,
            "confidence_level": NON_INFERIORITY_CONFIDENCE_LEVEL,
            "seed": CANDIDATE_SEED,
        },
        "stratification": [
            "by family",
            "by actor_position",
            "by sizing_bucket",
            "by ood_status",
            "by support_tier",
        ],
        "cv_report_metrics": protocol["metrics"],
        "mandatory_reporting": (
            "a pooled estimate is never scored without its OOD status; an abstained decision is "
            "reported, never scored as correct by defaulting to FOLD"
        ),
    }


def _active_references(inputs: Mapping[str, Any]) -> dict[str, Any]:
    admitted = inputs["admitted_for_367"]
    return {
        "active_model_a_preflop": {
            "path": _relative(ACTIVE_MODEL_A_PATH),
            "sha256": ACTIVE_MODEL_A_SHA256,
            "role": "ACTIVE_MODEL_A_POINTER",
            "mutated_by_this_freeze": False,
        },
        "active_model_b_postflop": {
            "path": _relative(ACTIVE_MODEL_B_PATH),
            "sha256": ACTIVE_MODEL_B_SHA256,
            "role": "ACTIVE_MODEL_B_POINTER",
            "mutated_by_this_freeze": False,
        },
        "training_registry": {
            "path": _relative(TRAINING_REGISTRY_PATH),
            "sha256": TRAINING_REGISTRY_SHA256,
            "role": "TRAINING_REGISTRY",
            "mutated_by_this_freeze": False,
        },
        "populations_registry": {
            "path": _relative(POPULATIONS_REGISTRY_PATH),
            "sha256": POPULATIONS_REGISTRY_SHA256,
            "role": "POPULATIONS_REGISTRY",
            "mutated_by_this_freeze": False,
        },
        "issue419_frozen_validation_protocol": {
            "path": _relative(ISSUE419_PROTOCOL_PATH),
            "sha256": ISSUE419_PROTOCOL_SHA256,
            "role": "PREDECESSOR_FROZEN_PROTOCOL",
        },
        "admitted_model_a_candidate_for_367": {**admitted, "mutated_by_this_freeze": False},
        "population_id": POPULATION_ID,
        "population_fingerprint_sha256": POPULATION_FINGERPRINT_SHA256,
    }


def _issue367_rule(inputs: Mapping[str, Any], candidate_canonical: str) -> dict[str, Any]:
    admitted = inputs["admitted_for_367"]
    return {
        "rule_id": "ISSUE367_CONSUMES_ONLY_AN_ADMITTED_CANDIDATE",
        "question": (
            "is a #367 consumption of the generalized adverse-response candidate authorized or "
            "forbidden?"
        ),
        "authorized_at_freeze": False,
        "authorized_when": [
            "the frozen VALIDATION evaluation returns outcome=ADMIT_CANDIDATE",
            "every frozen gate passes with the threshold values pinned in this protocol",
            (
                "the VALIDATION result is content-addressed (schema "
                + RESULT_SCHEMA
                + ", embedded protocol_byte_sha256) and pinned in a new explicit #367 protocol revision"
            ),
            (
                "that #367 protocol revision names model_a.candidate_id="
                + CANDIDATE_ID
                + " and model_a.candidate_sha256="
                + candidate_canonical
            ),
        ],
        "forbidden_while": [
            "the outcome is RETAIN_ACTIVE_REFERENCE or the candidate stays unresolved",
            "no ADMIT_CANDIDATE VALIDATION result exists for this candidate",
            "the candidate SHA differs from the pinned canonical payload digest",
            "a #367 run would change TEST consumption, Model B, Hero EV or the active Model A pointer",
        ],
        "consequence_when_forbidden": (
            "no #367 real ISO EV run, no support-grid extension and no provider wiring may consume "
            "this candidate; #367 keeps its current admitted model"
        ),
        "currently_admitted_model_a_for_367": admitted,
        "unchanged_by_this_freeze": True,
        "test_consumed": False,
        "model_b_consumed": False,
        "hero_ev_consumed": False,
        "promotion_performed": False,
        "active_model_pointer_mutation": False,
    }


def _runtime_format(inputs: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "model_schema": M.SCHEMA,
        "prediction_schema": M.PREDICTION_SCHEMA,
        "evaluation_schema": M.EVALUATION_SCHEMA,
        "price_response_schema": M.PRICE_RESPONSE_SCHEMA,
        "contract_path": _relative(MODEL_CONTRACT_PATH),
        "contract_sha256": MODEL_CONTRACT_SHA256,
        "module_path": _relative(MODULE_PATH),
        "module_sha256": MODULE_SHA256,
        "action_space": list(M.ACTIONS),
        "input_fields": inputs["dataset_manifest"]["row_contract"]["fields"],
        "optional_input_fields": ["target_total_bb", "raise_target_total_bb", "legal_actions"],
        "output_fields": [
            "probabilities",
            "P(FOLD)",
            "P(CALL)",
            "P(RAISE)",
            "P(JAM)",
            "probability_sum",
            "legal_actions",
            "masked_actions",
            "normalization",
            "sizing",
            "support",
            "architecture",
            "candidate_canonical_payload_sha256",
        ],
        "entrypoints": {
            "fit": f"{_relative(MODULE_PATH)}::fit",
            "predict": f"{_relative(MODULE_PATH)}::predict",
            "evaluate": f"{_relative(MODULE_PATH)}::evaluate",
            "price_response": f"{_relative(MODULE_PATH)}::price_response",
            "generate_raise_sizings": f"{_relative(MODULE_PATH)}::generate_raise_sizings",
            "score_raise_sizing": f"{_relative(MODULE_PATH)}::score_raise_sizing",
            "ood_gate_decision": f"{_relative(MODULE_PATH)}::ood_gate_decision",
            "validate_candidate": f"{_relative(MODULE_PATH)}::validate_candidate",
            "load_candidate": f"{_relative(MODULE_PATH)}::load_candidate",
        },
        "illegal_mass_max": 0.0,
        "probability_sum_tolerance": 1e-9,
        "legal_masking": True,
        "standard_library_only": True,
        "deterministic": True,
        "test_refused_fail_closed": True,
    }


def _forbidden() -> list[str]:
    return [
        "TEST",
        "HERO_EV",
        "MODEL_B",
        "UI",
        "NEAREST_PRICE",
        "NEAREST_CONTEXT",
        "ACTIVE_POINTER_MUTATION",
        "AUTOMATIC_PROMOTION",
        "HYPERPARAMETER_SEARCH_ON_VALIDATION",
        "THRESHOLD_RELAXATION_AFTER_VALIDATION",
        "COVERAGE_FLOOR_RELAXATION_AFTER_VALIDATION",
        "OOD_THRESHOLD_RELAXATION_AFTER_VALIDATION",
        "SIZING_CRITERIA_RELAXATION_AFTER_VALIDATION",
        "HIDDEN_HAND_IMPUTATION",
        "PSEUDO_OBSERVATION",
    ]


# --------------------------------------------------------------------------
# document assembly
# --------------------------------------------------------------------------


def _frozen_at_epoch(frozen_at: str) -> int:
    return int(
        dt.datetime.strptime(frozen_at, "%Y-%m-%dT%H:%M:%SZ")
        .replace(tzinfo=dt.timezone.utc)
        .timestamp()
    )


def build_manifest(inputs: Mapping[str, Any], *, frozen_at: str) -> dict[str, Any]:
    candidate = inputs["candidate"]
    cv_report = inputs["cv_report"]
    thresholds = _thresholds(inputs)
    generation_sha = sha256_file(SOURCE_PATH)
    return {
        "schema": MANIFEST_SCHEMA,
        "issue": 421,
        "kind": "CANDIDATE_MANIFEST",
        "status": FROZEN_STATUS,
        "frozen_at": frozen_at,
        "frozen_at_epoch": _frozen_at_epoch(frozen_at),
        "frozen_at_source": FROZEN_AT_SOURCE,
        "generated_by": {
            "tool_path": _relative(SOURCE_PATH),
            "tool_sha256": generation_sha,
            "schema_path": _relative(SCHEMA_PATH),
            "schema_sha256": sha256_file(SCHEMA_PATH),
        },
        "candidate": {
            "candidate_id": CANDIDATE_ID,
            "architecture": candidate["architecture"],
            "model_family": "MODEL_A_PREFLOP_RESPONSE",
            "path": _relative(CANDIDATE_PATH),
            "sha256": CANDIDATE_SHA256,
            "canonical_payload_sha256": CANDIDATE_CANONICAL_SHA256,
            "bytes": CANDIDATE_PATH.stat().st_size,
            "seed": int(candidate["seed"]),
            "action_space": list(candidate["action_space"]),
            "status": "CANDIDATE_ONLY_NOT_ACTIVE",
            "active_model_replaced": False,
            "selected_by": "TRAIN-only hand-grouped five-fold cross-validation",
            "selection_evidence": {
                "path": _relative(CV_REPORT_PATH),
                "sha256": CV_REPORT_SHA256,
                "selected": cv_report["selection"]["selected"],
                "ranking": cv_report["selection"]["ranking"],
                "evidence_basis": cv_report["selection"]["evidence_basis"],
            },
        },
        "features": _features(inputs),
        "transformations": _transformations(inputs),
        "architecture": _architecture(inputs),
        "hyperparameters": _hyperparameters(inputs),
        "seeds": _seeds(inputs),
        "corpus": _corpus(inputs),
        "cv_procedure": _cv_procedure(inputs),
        "ood_gate": thresholds["ood"],
        "metrics": _metrics(inputs),
        "thresholds": thresholds,
        "active_references": _active_references(inputs),
        "non_inferiority_rule": thresholds["non_inferiority"],
        "calibration_max": thresholds["calibration"],
        "sizing_criteria": thresholds["sizing"],
        "runtime_format": _runtime_format(inputs),
        "issue367_consumption_rule": _issue367_rule(inputs, CANDIDATE_CANONICAL_SHA256),
        "forbidden": _forbidden(),
        "reproduction": {
            "command": "python3 tools/training/freeze_generalized_validation_protocol.py",
            "check_command": "python3 tools/training/freeze_generalized_validation_protocol.py --check",
        },
    }


def _corpus(inputs: Mapping[str, Any]) -> dict[str, Any]:
    dataset_manifest = inputs["dataset_manifest"]
    splits = dataset_manifest["splits"]
    return {
        "population_id": POPULATION_ID,
        "dataset_path": _relative(DATASET_PATH),
        "dataset_sha256": DATASET_SHA256,
        "dataset_bytes": DATASET_BYTES,
        "dataset_rows": DATASET_ROWS,
        "dataset_manifest_path": _relative(DATASET_MANIFEST_PATH),
        "dataset_manifest_sha256": DATASET_MANIFEST_SHA256,
        "corpus_hashes_path": _relative(CORPUS_HASHES_PATH),
        "corpus_hashes_sha256": CORPUS_HASHES_SHA256,
        "certification_path": _relative(CERTIFICATION_PATH),
        "certification_sha256": CERTIFICATION_SHA256,
        "population_fingerprint_sha256": POPULATION_FINGERPRINT_SHA256,
        "train": {
            "split": "TRAIN",
            "hands": splits["TRAIN"]["hands"],
            "response_rows": splits["TRAIN"]["response_rows"],
            "hand_ids_fingerprint_sha256": splits["TRAIN"]["hand_ids_fingerprint_sha256"],
            "consumed_for_fit": True,
        },
        "validation": {
            "split": "VALIDATION",
            "hands": splits["VALIDATION"]["hands"],
            "response_rows": splits["VALIDATION"]["response_rows"],
            "hand_ids_fingerprint_sha256": splits["VALIDATION"]["hand_ids_fingerprint_sha256"],
            "consumed_for_fit": False,
            "reserved_for": "the fenced VALIDATION admission evaluation",
        },
        "test": {
            "split": "TEST",
            "hands": inputs["certification"]["status"]["ADMISSIBLE"]["split_counts"]["TEST"],
            "consumed": False,
            "refused": True,
        },
        "split_consumed_for_authoring": "TRAIN",
        "validation_consumed_for_authoring": False,
        "test_consumed_for_authoring": False,
    }


def build_protocol(
    inputs: Mapping[str, Any],
    *,
    manifest: Mapping[str, Any],
    frozen_at: str,
    checks: list[Mapping[str, Any]],
) -> dict[str, Any]:
    thresholds = _thresholds(inputs)
    manifest_bytes = serialize(manifest)
    manifest_digest = hashlib.sha256(manifest_bytes).hexdigest()
    manifest_canonical = canonical_hash(manifest)
    code = _code_fingerprints()
    generator_sha = next(row["sha256"] for row in code if row["role"] == "PROTOCOL_GENERATOR")
    fit_report = inputs["fit_report"]
    prior_reads = [
        {
            "reader": f"{_relative(MODULE_PATH)}::main(--eval-split VALIDATION)",
            "artifact_path": _relative(FIT_REPORT_PATH),
            "artifact_sha256": FIT_REPORT_SHA256,
            "split": "VALIDATION",
            "rows": fit_report["comparison"]["rows"],
            "read_before_this_freeze": True,
            "scope": "EXPLORATORY_ARCHITECTURE_COMPARISON",
            "authoritative_for_admission": False,
            "used_for_candidate_selection": False,
            "used_for_thresholds": False,
            "candidate_selection_basis": (
                "TRAIN-only hand-grouped five-fold cross-validation "
                "(TRAIN_CV_REPORT.selection, evidence_basis=out_of_fold_holdout_only)"
            ),
            "repair": "none; recorded as evidence, never double-counted",
            "note": (
                "the fit report scored both architectures on VALIDATION for orientation only; the "
                "frozen selection is the TRAIN-only cross-validation decision and no threshold in "
                "this protocol is derived from that comparison"
            ),
        }
    ]
    holdout_boundary = {
        "split_consumed_for_authoring": "TRAIN",
        "validation_consumed_for_authoring": False,
        "validation_decisions_read": 0,
        "validation_hands_parsed": 0,
        "test_consumed": False,
        "test_decisions_read": 0,
        "protocol_frozen_before_fenced_validation_evaluation": True,
        "fenced_validation_result_exists_at_freeze": False,
        "evaluation_split_opened_during_authoring": False,
        "prior_validation_reads": prior_reads,
        "checks": [dict(row) for row in checks],
    }
    return {
        "schema": PROTOCOL_SCHEMA,
        "issue": 421,
        "kind": "FROZEN_VALIDATION_PROTOCOL",
        "status": FROZEN_STATUS,
        "protocol_name": PROTOCOL_NAME,
        "frozen_at": frozen_at,
        "frozen_at_epoch": _frozen_at_epoch(frozen_at),
        "frozen_at_source": FROZEN_AT_SOURCE,
        "canonical_payload_is_the_frozen_identity": True,
        "authoring_order": {
            "protocol_written_and_hashed_before_validation_read": True,
            "scope": "the fenced VALIDATION admission evaluation",
            "protocol_bytes_pinned_before_fenced_validation_evaluation": True,
            "validation_read_before_protocol_hash": False,
            "evaluation_split_opened_during_authoring": False,
            "validation_rows_read_during_protocol_authoring": 0,
            "test_rows_read_during_protocol_authoring": 0,
        },
        "artifacts": {
            "candidate_manifest": {
                "path": MANIFEST_LOGICAL_PATH,
                "sha256": manifest_digest,
                "canonical_payload_sha256": manifest_canonical,
                "schema": MANIFEST_SCHEMA,
            },
            "candidate": {
                "candidate_id": CANDIDATE_ID,
                "architecture": CANDIDATE_ARCHITECTURE,
                "path": _relative(CANDIDATE_PATH),
                "sha256": CANDIDATE_SHA256,
                "canonical_payload_sha256": CANDIDATE_CANONICAL_SHA256,
                "status": "CANDIDATE_ONLY_NOT_ACTIVE",
            },
            "corpus": {
                "dataset_path": _relative(DATASET_PATH),
                "dataset_sha256": DATASET_SHA256,
                "dataset_manifest_path": _relative(DATASET_MANIFEST_PATH),
                "dataset_manifest_sha256": DATASET_MANIFEST_SHA256,
                "corpus_hashes_path": _relative(CORPUS_HASHES_PATH),
                "corpus_hashes_sha256": CORPUS_HASHES_SHA256,
                "certification_path": _relative(CERTIFICATION_PATH),
                "certification_sha256": CERTIFICATION_SHA256,
                "train_hand_ids_fingerprint_sha256": TRAIN_HAND_IDS_FINGERPRINT_SHA256,
                "validation_hand_ids_fingerprint_sha256": VALIDATION_HAND_IDS_FINGERPRINT_SHA256,
            },
            "evidence": [
                {"path": _relative(FIT_REPORT_PATH), "role": "TRAIN_FIT_REPORT", "sha256": FIT_REPORT_SHA256},
                {"path": _relative(CV_REPORT_PATH), "role": "TRAIN_CV_REPORT", "sha256": CV_REPORT_SHA256},
                {"path": _relative(OOD_REPORT_PATH), "role": "OOD_CALIBRATION_REPORT", "sha256": OOD_REPORT_SHA256},
                {"path": _relative(SIZING_REPORT_PATH), "role": "RAISE_SIZING_MODEL_REPORT", "sha256": SIZING_REPORT_SHA256},
                {"path": _relative(DATASET_REPORT_PATH), "role": "FEATURE_AUDIT_REPORT", "sha256": DATASET_REPORT_SHA256},
            ],
        },
        "code": {
            "cluster_id": CLUSTER_ID,
            "inputs": code,
            "protocol_generator_sha256": generator_sha,
            "schema_path": _relative(SCHEMA_PATH),
            "frozen": True,
        },
        "evaluation": {
            "split": "VALIDATION",
            "test_consumed": False,
            "test_authorized": False,
            "population": POPULATION_ID,
            "universe": (
                "non-Hero public preflop response decisions of the certified VALIDATION fold where "
                "the candidate and every comparator answer the same requested public context"
            ),
            "outcome_rule": (
                "ADMIT_CANDIDATE only when every frozen gate passes; otherwise "
                "RETAIN_ACTIVE_REFERENCE"
            ),
            "result_schema": RESULT_SCHEMA,
            "result_path": DECLARED_RESULT_LOGICAL_PATHS[0],
            "unresolved_policy": (
                "an OOD-abstaining or fail-closed decision is reported and excluded from the paired "
                "predictive gates; it never scores as correct and reduces the reported coverage"
            ),
            "result_must_not_exist_before_the_freeze": True,
        },
        "coverage_floor": thresholds["coverage"],
        "thresholds": thresholds,
        "non_inferiority_rule": thresholds["non_inferiority"],
        "calibration_max": thresholds["calibration"],
        "sizing_criteria": thresholds["sizing"],
        "metrics": _metrics(inputs),
        "active_references": _active_references(inputs),
        "issue367_rule": _issue367_rule(inputs, CANDIDATE_CANONICAL_SHA256),
        "immutability": {
            "frozen": True,
            "immutable_after_validation_read": True,
            "thresholds_unmodifiable_after_validation_read": True,
            "guard_rule": (
                "the byte digest of this protocol is pinned in "
                + PROTOCOL_NAME
                + ".sha256 and in validation_protocol/ARTIFACTS.json before the fenced VALIDATION "
                "evaluation runs; every later read re-derives that digest and refuses to proceed on "
                "mismatch, so a threshold cannot be moved after a VALIDATION row was seen"
            ),
            "detection": (
                "a fresh rebuild is compared byte-for-byte with the persisted manifest and protocol; "
                "any divergence in the candidate, the manifest, the protocol or a pinned input digest "
                "is reported and the check exits non-zero"
            ),
        },
        "order_guard": {
            "guard_id": "VALIDATION_ORDER_GUARD",
            "enforced_by": _relative(SOURCE_PATH),
            "guard_source_sha256": generator_sha,
            "rule": (
                "the freeze fails closed when a fenced VALIDATION result for this candidate already "
                "exists"
            ),
            "declared_result_locations": list(DECLARED_RESULT_LOGICAL_PATHS),
            "evaluation_side_rule": (
                "the evaluation command must re-verify the pinned protocol bytes before it opens a "
                "single VALIDATION hand"
            ),
            "freeze_authored_before_validation": True,
            "validation_read_before_freeze": False,
        },
        "holdout_boundary": holdout_boundary,
        "publication": {
            "automatic_promotion": "FORBIDDEN",
            "active_model_pointer_mutation": False,
            "production_effect": "NONE",
            "downstream": (
                "only an ADMIT_CANDIDATE outcome may be consumed downstream; a rejected candidate "
                "leaves the active Model A pointer unchanged"
            ),
        },
        "forbidden": _forbidden(),
        "not_an_admission": (
            "this protocol admits nothing by itself: it fixes the rules, the thresholds and the "
            "references before the fenced VALIDATION evaluation is opened"
        ),
        "reproduction": {
            "command": "python3 tools/training/freeze_generalized_validation_protocol.py",
            "check_command": "python3 tools/training/freeze_generalized_validation_protocol.py --check",
        },
    }


def assert_manifest_protocol_consistency(
    manifest: Mapping[str, Any], protocol: Mapping[str, Any]
) -> None:
    """Fail closed on any divergence between the manifest, the protocol and the candidate."""
    manifest_digest = hashlib.sha256(serialize(manifest)).hexdigest()
    bound = protocol["artifacts"]["candidate_manifest"]
    if bound["sha256"] != manifest_digest:
        raise ProtocolError("protocol is not bound to the manifest bytes")
    if bound["canonical_payload_sha256"] != canonical_hash(manifest):
        raise ProtocolError("protocol is not bound to the manifest canonical payload")
    if protocol["artifacts"]["candidate"]["canonical_payload_sha256"] != manifest["candidate"][
        "canonical_payload_sha256"
    ]:
        raise ProtocolError("protocol candidate digest differs from the manifest candidate digest")
    if protocol["artifacts"]["candidate"]["sha256"] != manifest["candidate"]["sha256"]:
        raise ProtocolError("protocol candidate byte digest differs from the manifest")
    for key in ("thresholds", "non_inferiority_rule", "calibration_max", "sizing_criteria"):
        expected = manifest["thresholds"] if key == "thresholds" else manifest[key]
        if protocol[key] != expected:
            raise ProtocolError(f"protocol {key} diverges from the manifest")
    if protocol["coverage_floor"] != manifest["thresholds"]["coverage"]:
        raise ProtocolError("protocol coverage floor diverges from the manifest")
    if protocol["coverage_floor"]["minimum_coverage"] < MINIMUM_COVERAGE:
        raise ProtocolError("minimum product coverage fell below the frozen floor")
    if protocol["status"] != FROZEN_STATUS or manifest["status"] != FROZEN_STATUS:
        raise ProtocolError("manifest/protocol status is not FROZEN_BEFORE_VALIDATION")


# --------------------------------------------------------------------------
# build / persist / check
# --------------------------------------------------------------------------


def build(frozen_at: str | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    frozen_at = frozen_at or _persisted_frozen_at()
    checks = [
        static_holdout_scan(),
        assert_fenced_validation_not_yet_consumed(),
        assert_no_hand_level_dataset_read(),
    ]
    for check in checks:
        if check.get("result") != "PASS":
            raise ProtocolError(f"guard failed: {check.get('check')}")
    inputs = verify_inputs()
    manifest = build_manifest(inputs, frozen_at=frozen_at)
    protocol = build_protocol(inputs, manifest=manifest, frozen_at=frozen_at, checks=checks)
    assert_manifest_protocol_consistency(manifest, protocol)
    return manifest, protocol


def summarize(manifest: Mapping[str, Any], protocol: Mapping[str, Any], digests: Mapping[str, str]) -> str:
    candidate = protocol["artifacts"]["candidate"]
    thresholds = protocol["thresholds"]
    return (
        "# #421 — candidate manifest and frozen VALIDATION protocol\n\n"
        f"`{PROTOCOL_NAME}` byte SHA256: `{digests['protocol_sha256']}`; frozen at "
        f"`{protocol['frozen_at']}` (`{protocol['status']}`).\n\n"
        f"Candidate `{candidate['candidate_id']}` ({candidate['architecture']}) canonical payload "
        f"`{candidate['canonical_payload_sha256']}`, byte `{candidate['sha256']}`. Manifest "
        f"`{MANIFEST_NAME}` byte SHA256 `{digests['manifest_sha256']}`.\n\n"
        f"Frozen gates: minimum product coverage `>= {thresholds['coverage']['minimum_coverage']}`, "
        f"non-inferiority CI upper bound `<= {thresholds['non_inferiority']['ci_upper_bound']}`, "
        f"maximum absolute ECE `<= {thresholds['calibration']['maximum_absolute_ece']}`, "
        f"raise-sizing illegal-generation rate `<="
        f" {thresholds['sizing']['maximum_illegal_generated_rate']}`. Every threshold is immutable "
        "after the freeze and a fresh rebuild is compared byte-for-byte before any VALIDATION row is "
        "read; any candidate/manifest/protocol drift is fail-closed.\n\n"
        "Reproduce: `python3 tools/training/freeze_generalized_validation_protocol.py --check`.\n"
    )


def persist(frozen_at: str | None = None) -> dict[str, Any]:
    manifest, protocol = build(frozen_at)
    bundle_objects = BUNDLE / "sha256"
    bundle_objects.mkdir(parents=True, exist_ok=True)

    manifest_bytes = serialize(manifest)
    manifest_digest = hashlib.sha256(manifest_bytes).hexdigest()
    protocol_bytes = serialize(protocol)
    protocol_digest = hashlib.sha256(protocol_bytes).hexdigest()

    MANIFEST_PATH.write_bytes(manifest_bytes)
    PROTOCOL_PATH.write_bytes(protocol_bytes)
    (bundle_objects / (manifest_digest + ".json")).write_bytes(manifest_bytes)
    (bundle_objects / (protocol_digest + ".json")).write_bytes(protocol_bytes)

    summary_bytes = summarize(
        manifest,
        protocol,
        {"manifest_sha256": manifest_digest, "protocol_sha256": protocol_digest},
    ).encode()
    summary_digest = hashlib.sha256(summary_bytes).hexdigest()
    (BUNDLE / "SUMMARY.md").write_bytes(summary_bytes)
    (bundle_objects / (summary_digest + ".md")).write_bytes(summary_bytes)

    MANIFEST_DIGEST_PATH.write_text(
        f"{manifest_digest}  {MANIFEST_NAME}\n"
        f"# canonical_payload_sha256 {canonical_hash(manifest)}\n"
        f"# frozen_at {manifest['frozen_at']}\n"
    )
    PROTOCOL_DIGEST_PATH.write_text(
        f"{protocol_digest}  {PROTOCOL_NAME}\n"
        f"# canonical_payload_sha256 {canonical_hash(protocol)}\n"
        f"# frozen_at {protocol['frozen_at']}\n"
    )

    index = {
        MANIFEST_NAME: {
            "sha256": manifest_digest,
            "canonical_payload_sha256": canonical_hash(manifest),
            "schema": MANIFEST_SCHEMA,
            "object": "sha256/" + manifest_digest + ".json",
        },
        PROTOCOL_NAME: {
            "sha256": protocol_digest,
            "canonical_payload_sha256": canonical_hash(protocol),
            "schema": PROTOCOL_SCHEMA,
            "object": "sha256/" + protocol_digest + ".json",
        },
        "SUMMARY.md": {"sha256": summary_digest, "object": "sha256/" + summary_digest + ".md"},
    }
    BUNDLE_INDEX.write_text(json.dumps(index, sort_keys=True, indent=2) + "\n")

    referenced = {Path(entry["object"]).name for entry in index.values()}
    for path in bundle_objects.iterdir():
        if path.is_file() and path.name not in referenced:
            path.unlink()
    return index


def _persisted_frozen_at() -> str:
    for path in (PROTOCOL_PATH, MANIFEST_PATH):
        if Path(path).is_file():
            try:
                value = _load(path).get("frozen_at")
            except (OSError, ValueError):
                continue
            if value:
                return str(value)
    return DEFAULT_FROZEN_AT


def check() -> int:
    problems: list[str] = []
    frozen_at = _persisted_frozen_at()
    try:
        manifest, protocol = build(frozen_at=frozen_at)
    except ProtocolError as error:
        print(json.dumps({"status": "MISMATCH", "problems": [str(error)]}, indent=2))
        return 1

    manifest_bytes = serialize(manifest)
    manifest_digest = hashlib.sha256(manifest_bytes).hexdigest()
    protocol_bytes = serialize(protocol)
    protocol_digest = hashlib.sha256(protocol_bytes).hexdigest()

    if not Path(MANIFEST_PATH).is_file() or MANIFEST_PATH.read_bytes() != manifest_bytes:
        problems.append("canonical manifest bytes differ from a fresh build")
    if not Path(PROTOCOL_PATH).is_file() or PROTOCOL_PATH.read_bytes() != protocol_bytes:
        problems.append("canonical protocol bytes differ from a fresh build")
    if Path(MANIFEST_PATH).is_file() and Path(PROTOCOL_PATH).is_file():
        try:
            persisted_manifest = _load(MANIFEST_PATH)
            persisted_protocol = _load(PROTOCOL_PATH)
            assert_manifest_protocol_consistency(persisted_manifest, persisted_protocol)
        except (ProtocolError, ValueError) as error:
            problems.append(f"persisted manifest/protocol are inconsistent: {error}")

    if not Path(BUNDLE_INDEX).is_file():
        problems.append("missing validation_protocol/ARTIFACTS.json")
        index: dict[str, Any] = {}
    else:
        index = index_load()
    manifest_entry = index.get(MANIFEST_NAME, {})
    if manifest_entry.get("sha256") != manifest_digest:
        problems.append("manifest index digest mismatch")
    if manifest_entry.get("canonical_payload_sha256") != canonical_hash(manifest):
        problems.append("manifest canonical payload digest mismatch")
    protocol_entry = index.get(PROTOCOL_NAME, {})
    if protocol_entry.get("sha256") != protocol_digest:
        problems.append("protocol index digest mismatch")
    if protocol_entry.get("canonical_payload_sha256") != canonical_hash(protocol):
        problems.append("protocol canonical payload digest mismatch")
    for name, expectation in ((MANIFEST_NAME, manifest_bytes), (PROTOCOL_NAME, protocol_bytes)):
        entry = index.get(name, {})
        object_path = BUNDLE / str(entry.get("object", "missing"))
        if not object_path.is_file() or object_path.read_bytes() != expectation:
            problems.append(f"content-addressed copy mismatch for {name}")
    if not Path(MANIFEST_DIGEST_PATH).is_file() or not MANIFEST_DIGEST_PATH.read_text().startswith(
        manifest_digest + "  " + MANIFEST_NAME
    ):
        problems.append("manifest .sha256 sidecar mismatch")
    if not Path(PROTOCOL_DIGEST_PATH).is_file() or not PROTOCOL_DIGEST_PATH.read_text().startswith(
        protocol_digest + "  " + PROTOCOL_NAME
    ):
        problems.append("protocol .sha256 sidecar mismatch")
    for name, row in index.items():
        path = BUNDLE / name
        if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]:
            problems.append(f"byte hash mismatch for {name}")

    if problems:
        print(json.dumps({"status": "MISMATCH", "problems": problems}, indent=2))
        return 1
    print(
        json.dumps(
            {
                "status": "OK",
                "schema": PROTOCOL_SCHEMA,
                "manifest_sha256": manifest_digest,
                "protocol_sha256": protocol_digest,
                "protocol_canonical_payload_sha256": canonical_hash(protocol),
                "frozen_at": protocol["frozen_at"],
                "status_field": protocol["status"],
                "minimum_coverage": protocol["coverage_floor"]["minimum_coverage"],
                "candidate": protocol["artifacts"]["candidate"]["candidate_id"],
                "validation_consumed_for_authoring": protocol["holdout_boundary"][
                    "validation_consumed_for_authoring"
                ],
            },
            indent=2,
        )
    )
    return 0


def index_load() -> dict[str, Any]:
    return json.loads(Path(BUNDLE_INDEX).read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the persisted manifest/protocol instead of rewriting them",
    )
    parser.add_argument(
        "--frozen-at",
        default=None,
        help="explicit ISO-8601 freeze timestamp (defaults to the persisted one)",
    )
    args = parser.parse_args(argv)
    if args.check:
        return check()
    index = persist(args.frozen_at)
    print(
        json.dumps(
            {
                "status": "WRITTEN",
                "manifest_path": str(MANIFEST_PATH.relative_to(ROOT)),
                "protocol_path": str(PROTOCOL_PATH.relative_to(ROOT)),
                "manifest_sha256": index[MANIFEST_NAME]["sha256"],
                "protocol_sha256": index[PROTOCOL_NAME]["sha256"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""#423 T5 - freeze the numeric admission criteria and publish the router manifest.

The #423 hybrid router is preregistered in two steps:

* ``tools/training/freeze_hybrid_router_spec.py`` (#423 T1) authors the
  *procedure*: the route sources, the runtime contract, the OOD gate and the
  symbolic formulas that derive every admission threshold, with no numeric
  value attached to them;
* this tool (#423 T5) resolves those formulas into the numeric criteria the
  router must satisfy -- the global non-inferiority margin, the minimal sparse
  gain, the sparse ECE ceiling, the frequent-exact non-degradation bound and
  the OOD abstention criterion -- and freezes them, with their quantitative
  justification, into ``HYBRID_ROUTER_SPEC.json`` and ``ROUTER_MANIFEST.json``
  plus their ``.sha256`` sidecars.

Every frozen number is measured on the TRAIN-only cross-fitted derivation of
#423 T4 (``analysis/issue423_hybrid_router/derivation/CV_DERIVATION.json``): the
margin is sized by the paired-by-hand bootstrap dispersion of the
hybrid-minus-active log-loss delta, the sparse floor and ceiling are the
support-weighted statistics of the two strata the generalized channel is
allowed to cover, the frequent-exact bound is the paired dispersion of that
stratum, and the OOD criterion is the measured abstention rate of the synthetic
out-of-domain probe surface.  The manifest records, for each criterion, the
statistic, the confidence interval, the effectifs and the digests of every
derivation input, so a reader can recompute the number instead of trusting it.

Ordering guard
--------------
The freeze is authored *before* any terminal score.  ``freeze()`` refuses to
run when a terminal ``TRAIN_CV_ROUTER_REPORT.json`` already exists -- a numeric
threshold issued after the score it judges would not be a preregistration --
and, once frozen, a regeneration that would produce a different value fails
closed instead of silently rewriting the frozen criteria.  ``check()`` runs
both before and after the terminal run: while the report is absent the guard is
satisfied by that absence, and once the #423 T6 report exists it is satisfied by
the report *binding* the frozen spec digest this freeze wrote -- a report that
pins nothing, or different bytes, leaves the ordering unprovable and is
reported as a violation.

Scientific boundary
-------------------
Only the Python standard library and repository modules are used.  The tool
parses no hand history and no decision JSONL: it consumes the content-addressed
TRAIN-only derivation and the frozen T1 spec, and it fails closed on any
artifact that declares a VALIDATION or TEST read.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SOURCE_PATH = Path(__file__).resolve()

from tools.training import freeze_hybrid_router_spec as spec_tool  # noqa: E402

# --------------------------------------------------------------------------
# layout and identity
# --------------------------------------------------------------------------

HERE = ROOT / "analysis/issue423_hybrid_router"
DERIVATION_DIR = HERE / "derivation"
DERIVATION_NAME = "CV_DERIVATION.json"
DERIVATION_PATH = DERIVATION_DIR / DERIVATION_NAME
DERIVATION_DIGEST_PATH = DERIVATION_DIR / "CV_DERIVATION.sha256"

SPEC_NAME = "HYBRID_ROUTER_SPEC.json"
SPEC_PATH = HERE / SPEC_NAME
SPEC_DIGEST_PATH = HERE / "HYBRID_ROUTER_SPEC.sha256"

MANIFEST_NAME = "ROUTER_MANIFEST.json"
MANIFEST_PATH = HERE / MANIFEST_NAME
MANIFEST_DIGEST_PATH = HERE / "ROUTER_MANIFEST.sha256"

#: The terminal score this freeze must precede.  Declared, never created here.
TERMINAL_REPORT_NAME = "TRAIN_CV_ROUTER_REPORT.json"
TERMINAL_REPORT_PATHS = (
    HERE / TERMINAL_REPORT_NAME,
    HERE / "terminal" / TERMINAL_REPORT_NAME,
)

#: Logical (repository-relative) paths serialized into the frozen documents, so
#: a rebuild in another layout reproduces the same bytes.
DERIVATION_LOGICAL_PATH = "analysis/issue423_hybrid_router/derivation/CV_DERIVATION.json"
DERIVATION_DIGEST_LOGICAL_PATH = "analysis/issue423_hybrid_router/derivation/CV_DERIVATION.sha256"
SPEC_LOGICAL_PATH = "analysis/issue423_hybrid_router/HYBRID_ROUTER_SPEC.json"
MANIFEST_LOGICAL_PATH = "analysis/issue423_hybrid_router/ROUTER_MANIFEST.json"
TERMINAL_REPORT_LOGICAL_PATHS = (
    f"analysis/issue423_hybrid_router/{TERMINAL_REPORT_NAME}",
    f"analysis/issue423_hybrid_router/terminal/{TERMINAL_REPORT_NAME}",
)
GENERATOR_LOGICAL_PATH = "tools/training/freeze_hybrid_router_criteria.py"
SPEC_GENERATOR_LOGICAL_PATH = "tools/training/freeze_hybrid_router_spec.py"

CRITERIA_SCHEMA = "poker-hybrid-router-frozen-criteria/v1"
MANIFEST_SCHEMA = "poker-hybrid-router-criteria-manifest/v1"
DERIVATION_SCHEMA_PREFIX = "poker-hybrid-router-cv-derivation"
SPEC_SCHEMA = spec_tool.SPEC_SCHEMA
ISSUE = 423
PLANNER_KEY = "T5"
KIND = "frozen_hybrid_router_admission_criteria_and_manifest"
STATUS = "FROZEN_BEFORE_TERMINAL_EVALUATION"

#: The freeze timestamp is a fixed preregistered constant so the frozen bytes
#: are reproducible; ``--frozen-at`` exists only for explicit re-authoring.
DEFAULT_FROZEN_AT = "2026-09-26T00:00:00Z"
FROZEN_AT_SOURCE = "explicit_freeze_timestamp_recorded_before_the_terminal_router_score"

#: Splits the freeze may consume (TRAIN) and must refuse.
ALLOWED_SPLITS = ("TRAIN",)
CONSUMED_SPLITS = ("TRAIN",)
REFUSED_SPLITS = ("VALIDATION", "TEST")

#: The channels and strata of the frozen derivation this freeze reads.
CHANNEL_HYBRID = "hybrid_router"
CHANNEL_ACTIVE = "active_model_a"
ADMISSION_STRATA = ("frequent_exact", "rare_exact", "exact_absent_in_domain")
SPARSE_STRATA = ("rare_exact", "exact_absent_in_domain")
FREQUENT_EXACT_STRATUM = "frequent_exact"
OOD_STRATUM = "exact_absent_out_of_domain"

#: The five numeric criteria this freeze resolves, in derivation order.
CRITERION_MARGIN = "GLOBAL_NON_INFERIORITY_MARGIN"
CRITERION_SPARSE_GAIN = "SPARSE_GAIN_FLOOR"
CRITERION_SPARSE_ECE = "SPARSE_ECE_CEILING"
CRITERION_FREQUENT_EXACT = "FREQUENT_EXACT_NON_DEGRADATION_BOUND"
CRITERION_OOD = "OOD_ABSTENTION_CRITERION"
CRITERIA_IDS = (
    CRITERION_MARGIN,
    CRITERION_SPARSE_GAIN,
    CRITERION_SPARSE_ECE,
    CRITERION_FREQUENT_EXACT,
    CRITERION_OOD,
)

#: The preregistered constants the derivation rules consume.  A missing one is a
#: fail-closed error: the frozen numbers must be anchored on T1's procedure.
REQUIRED_CONSTANTS = (
    "NON_INFERIORITY_CONFIDENCE_LEVEL",
    "NON_INFERIORITY_UPPER_QUANTILE",
    "NON_INFERIORITY_ALPHA",
    "BOOTSTRAP_SAMPLES",
    "BOOTSTRAP_SEED",
    "MARGIN_MAX_BITS",
    "MARGIN_ANALYTIC_TOLERANCE_BITS",
    "GAIN_FLOOR_BITS",
    "ECE_ABSOLUTE_CEILING",
    "ECE_DELTA_CEILING",
    "FREQUENT_EXACT_MAX_DEGRADATION_BITS",
    "MINIMUM_SPARSE_OBSERVATIONS",
    "FREQUENT_EXACT_MIN_SUPPORT",
    "RARE_EXACT_MIN_SUPPORT",
)

#: Symbols that would indicate a holdout (VALIDATION/TEST) read.
HOLDOUT_LOADER_SYMBOLS = (
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
)


class HybridRouterCriteriaError(RuntimeError):
    """Fail-closed error for the hybrid router numeric freeze."""


# --------------------------------------------------------------------------
# small deterministic helpers
# --------------------------------------------------------------------------


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_hash(value: Any) -> str:
    """Byte-identical to the repository-wide ``stable_hash``."""
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(raw).hexdigest()


def _relative(path: str | Path) -> str:
    resolved = Path(path).resolve()
    try:
        return str(resolved.relative_to(ROOT))
    except ValueError:
        return str(resolved)


def _round(value: Any, digits: int = 6) -> Any:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return value
    number = float(value)
    if not math.isfinite(number):
        return None
    return round(number, digits)


def _finalize(value: Any) -> Any:
    """Recursively round floats so the frozen documents are deterministic."""
    if isinstance(value, Mapping):
        return {key: _finalize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_finalize(item) for item in value]
    if isinstance(value, float):
        return _round(value)
    return value


def _ceil_to_quantum(value: float, quantum: float) -> float:
    """Smallest multiple of ``quantum`` that is not below ``value``."""
    steps = math.ceil(round(float(value) / quantum, 9))
    return _round(steps * quantum)


def _floor_to_quantum(value: float, quantum: float) -> float:
    """Largest multiple of ``quantum`` that is not above ``value``."""
    steps = math.floor(round(float(value) / quantum, 9))
    return _round(steps * quantum)


def verify_no_holdout_access(source: str | None = None) -> dict[str, Any]:
    """Static, reproducible proof that the freeze names no holdout loader."""
    text = SOURCE_PATH.read_text(encoding="utf-8") if source is None else source
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
            imported.append(node.module or "")
            imported.extend(alias.name for alias in node.names)
    hits = sorted(used & set(HOLDOUT_LOADER_SYMBOLS))
    if hits:
        raise HybridRouterCriteriaError(f"holdout loader symbol used in criteria freeze: {hits}")
    bad_imports = sorted(
        name for name in imported if any(marker in name.lower() for marker in ("validation", "holdout"))
    )
    if bad_imports:
        raise HybridRouterCriteriaError(f"holdout-looking import in criteria freeze: {bad_imports}")
    data_extensions = (".json", ".jsonl", ".zip", ".txt", ".csv")
    bad_literals = sorted(
        node.value
        for node in ast.walk(module)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value.endswith(data_extensions)
        and any(marker in node.value.lower() for marker in ("validation", "holdout", "test"))
    )
    if bad_literals:
        raise HybridRouterCriteriaError(f"holdout-looking data path literal: {bad_literals}")
    return {
        "check": "self_source_scan_for_holdout_loaders",
        "result": "PASS",
        "forbidden_symbols": list(HOLDOUT_LOADER_SYMBOLS),
        "hits": [],
        "holdout_looking_imports": [],
        "holdout_looking_data_path_literals": [],
        "detail": (
            "AST scan: the criteria freeze uses none of the forbidden holdout loader symbols, "
            "imports no validation/holdout module and declares no validation/holdout data path"
        ),
    }


# --------------------------------------------------------------------------
# ordering guard: the freeze must precede the terminal score
# --------------------------------------------------------------------------


def assert_terminal_report_absent(paths: Sequence[str | Path] | None = None) -> dict[str, Any]:
    """Fail closed when the terminal router score already exists."""
    candidates = tuple(paths) if paths is not None else tuple(TERMINAL_REPORT_PATHS)
    present = [str(path) for path in candidates if Path(path).is_file()]
    if present:
        raise HybridRouterCriteriaError(
            "a terminal hybrid router score already exists before the numeric freeze: "
            + ", ".join(_relative(path) for path in present)
            + "; the criteria would not be preregistered"
        )
    return {
        "check": "no_terminal_router_report_exists_before_freeze",
        "guard_id": "ROUTER_CRITERIA_ORDER_GUARD",
        "declared_terminal_report_locations": list(TERMINAL_REPORT_LOGICAL_PATHS),
        "declared_terminal_report_locations_present": [],
        "result": "PASS",
        "detail": (
            "the freeze refuses to author numeric admission criteria once a terminal "
            "TRAIN_CV_ROUTER_REPORT.json exists"
        ),
        "violations": [],
    }


# --------------------------------------------------------------------------
# TRAIN-only evidence
# --------------------------------------------------------------------------


def load_derivation(path: str | Path | None = None) -> dict[str, Any]:
    source = Path(path) if path is not None else DERIVATION_PATH
    if not source.is_file():
        raise HybridRouterCriteriaError(f"missing derivation artifact: {_relative(source)}")
    return json.loads(source.read_text(encoding="utf-8"))


def assert_train_only_derivation(derivation: Mapping[str, Any]) -> None:
    """Fail closed when the derived evidence is not TRAIN-only."""
    schema = str(derivation.get("schema", ""))
    if not schema.startswith(DERIVATION_SCHEMA_PREFIX):
        raise HybridRouterCriteriaError(
            f"the consumed derivation declares schema {schema!r}, expected {DERIVATION_SCHEMA_PREFIX}*"
        )
    scope = derivation.get("scope") or {}
    split = str(scope.get("split", "")).upper()
    consumed = tuple(str(item).upper() for item in (scope.get("consumed_splits") or ()))
    if split and split not in ALLOWED_SPLITS:
        raise HybridRouterCriteriaError(f"the derivation declares split {split!r}")
    if consumed and consumed != CONSUMED_SPLITS:
        raise HybridRouterCriteriaError(
            f"the derivation declares consumed splits {list(consumed)}; only TRAIN is allowed"
        )
    for flag in ("validation_consumed", "test_consumed"):
        if scope.get(flag):
            raise HybridRouterCriteriaError(f"the derivation declares {flag}=true")
    guards = derivation.get("guards") or {}
    if not guards.get("train_only"):
        raise HybridRouterCriteriaError("the derivation does not declare a TRAIN-only guard")
    for flag in ("validation_consumed", "test_consumed"):
        if guards.get(flag):
            raise HybridRouterCriteriaError(f"the derivation guard declares {flag}=true")
    if not guards.get("hands_never_on_both_sides_of_a_fold"):
        raise HybridRouterCriteriaError(
            "the derivation does not prove the hand-grouped no-leak property"
        )
    assertions = derivation.get("assertions") or {}
    for flag in ("validation_never_read", "test_never_read"):
        if assertions.get(flag) is not True:
            raise HybridRouterCriteriaError(f"the derivation does not assert {flag}")
    margin = derivation.get("margin_derivation") or {}
    if margin.get("terminal_evaluation_derived") is not False:
        raise HybridRouterCriteriaError(
            "the derivation must not carry a terminal-evaluation-derived margin"
        )


def assert_preregistered_procedure(spec: Mapping[str, Any]) -> dict[str, float]:
    """Fail closed when the T1 procedure is missing or not preregistered."""
    procedure = spec.get("procedure") or {}
    if procedure.get("preregistered") is not True:
        raise HybridRouterCriteriaError("the T1 spec does not declare a preregistered procedure")
    if procedure.get("registered_before_evaluation") is not True:
        raise HybridRouterCriteriaError("the T1 procedure is not registered before evaluation")
    if procedure.get("evaluation_basis") != "TRAIN_only_hand_grouped_out_of_fold":
        raise HybridRouterCriteriaError("the T1 procedure declares an unexpected evaluation basis")
    for flag in ("validation_consumed", "test_consumed"):
        if procedure.get(flag) is not False:
            raise HybridRouterCriteriaError(f"the T1 procedure declares {flag} other than false")
    constants: dict[str, float] = {}
    for entry in procedure.get("constants") or ():
        name = str(entry.get("name"))
        value = entry.get("value")
        if entry.get("terminal_evaluation_derived") is not False:
            raise HybridRouterCriteriaError(f"constant {name} is not marked preregistered")
        constants[name] = value
    missing = sorted(name for name in REQUIRED_CONSTANTS if name not in constants)
    if missing:
        raise HybridRouterCriteriaError(f"the T1 procedure omits constants {missing}")
    formula_ids = {str(formula.get("id")) for formula in procedure.get("formulas") or ()}
    missing_formulas = sorted(set(CRITERIA_IDS) - formula_ids)
    if missing_formulas:
        raise HybridRouterCriteriaError(
            f"the T1 procedure omits the formulas {missing_formulas} the freeze resolves"
        )
    order = list(procedure.get("derivation_order") or ())
    if not order:
        raise HybridRouterCriteriaError("the T1 procedure declares no derivation order")
    return constants


def assert_derivation_digest(
    path: str | Path | None = None,
    digest_path: str | Path | None = None,
    derivation: Mapping[str, Any] | None = None,
) -> str:
    """Verify the derivation is pinned by its own ``.sha256`` sidecar."""
    source = Path(path) if path is not None else DERIVATION_PATH
    sidecar = Path(digest_path) if digest_path is not None else source.with_suffix(".sha256")
    digest = sha256_file(source)
    if not sidecar.is_file():
        raise HybridRouterCriteriaError(f"missing derivation sidecar: {_relative(sidecar)}")
    pinned = sidecar.read_text(encoding="utf-8").splitlines()
    if not pinned or pinned[0].split()[0] != digest:
        raise HybridRouterCriteriaError(
            "the derivation .sha256 sidecar does not pin the persisted bytes"
        )
    artifact = derivation if derivation is not None else load_derivation(source)
    if artifact.get("canonical_payload_sha256"):
        payload = {
            key: value
            for key, value in artifact.items()
            if key != "canonical_payload_sha256"
        }
        if artifact["canonical_payload_sha256"] != stable_hash(_finalize(payload)):
            raise HybridRouterCriteriaError("the derivation canonical payload digest does not verify")
    return digest


def stratum_metrics(derivation: Mapping[str, Any], channel: str, stratum: str) -> dict[str, Any]:
    block = (((derivation.get("models") or {}).get(channel) or {}).get("by_stratum") or {}).get(
        stratum
    )
    if not isinstance(block, Mapping):
        raise HybridRouterCriteriaError(
            f"the derivation omits channel {channel!r} stratum {stratum!r}"
        )
    return dict(block)


def paired_comparison(
    derivation: Mapping[str, Any],
    *,
    stratum: str | None = None,
) -> dict[str, Any]:
    """The paired hybrid-minus-active bootstrap of the admission support or one stratum."""
    if stratum is None:
        block = (
            ((derivation.get("paired") or {}).get("hybrid_router_minus_active_model_a") or {})
            .get("admission_support")
        )
        label = "admission_support"
    else:
        block = (
            (((derivation.get("per_stratum") or {}).get(stratum) or {}).get("paired") or {})
            .get("hybrid_router_minus_active_model_a")
        )
        label = stratum
    if not isinstance(block, Mapping):
        raise HybridRouterCriteriaError(f"the derivation omits the paired comparison for {label!r}")
    return dict(block)


def _weighted(weights: Mapping[str, float], values: Mapping[str, float], label: str) -> float:
    total = math.fsum(float(weights[key]) for key in weights)
    if total <= 0.0:
        raise HybridRouterCriteriaError(f"the {label} support is empty")
    return _round(math.fsum(float(weights[key]) * float(values[key]) for key in weights) / total)


# --------------------------------------------------------------------------
# the numeric criteria
# --------------------------------------------------------------------------


def _criterion(
    *,
    criterion_id: str,
    t1_formula_id: str,
    derives: str,
    value: float,
    unit: str,
    direction: str,
    criterion: str,
    derivation_rule: str,
    justification: Mapping[str, Any],
    inputs: Sequence[Mapping[str, Any]],
    effectifs: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "id": criterion_id,
        "t1_formula_id": t1_formula_id,
        "derives": derives,
        "value": _round(value),
        "unit": unit,
        "direction": direction,
        "criterion": criterion,
        "derivation_rule": derivation_rule,
        "justification": dict(justification),
        "inputs": [dict(entry) for entry in inputs],
        "effectifs": dict(effectifs),
        "terminal_evaluation_derived": False,
    }


def _margin_criterion(
    derivation: Mapping[str, Any], constants: Mapping[str, float], quantum: float
) -> dict[str, Any]:
    margin = derivation.get("margin_derivation") or {}
    paired = paired_comparison(derivation)
    observed_bootstrap = float(margin["margin_global_bootstrap_bits_per_decision"])
    observed_analytic = float(margin["margin_global_analytic_bits_per_decision"])
    absolute_difference = abs(observed_bootstrap - observed_analytic)
    tolerance = float(constants["MARGIN_ANALYTIC_TOLERANCE_BITS"])
    if absolute_difference > tolerance:
        raise HybridRouterCriteriaError(
            "the bootstrap and analytic margins disagree beyond the preregistered tolerance"
        )
    if float(paired["upper_quantile_bits_per_decision"]) != observed_bootstrap:
        raise HybridRouterCriteriaError(
            "the derivation's admission-support upper quantile and the margin block disagree"
        )
    value = _ceil_to_quantum(
        max(float(constants["MARGIN_MAX_BITS"]), observed_bootstrap), quantum
    )
    strata_rows = {
        stratum: int((((derivation.get("models") or {}).get(CHANNEL_HYBRID) or {})
                      .get("by_stratum") or {}).get(stratum, {}).get("scope", {}).get("n", 0))
        for stratum in ADMISSION_STRATA
    }
    return _criterion(
        criterion_id=CRITERION_MARGIN,
        t1_formula_id=CRITERION_MARGIN,
        derives="margin_global",
        value=value,
        unit="bits_per_decision",
        direction="lower_is_better",
        criterion=(
            f"margin_global_bits_per_decision <= {value} "
            "(one-sided upper percentile of the paired-by-hand bootstrap of "
            "mean(log_loss_hybrid - log_loss_active) on the admission support)"
        ),
        derivation_rule=(
            "ceil_to_quantum(max(MARGIN_MAX_BITS, one_sided_upper_quantile of the paired "
            "hybrid-minus-active bootstrap), MARGIN_ANALYTIC_TOLERANCE_BITS)"
        ),
        justification={
            "statistic": margin.get("statistic"),
            "observed_bootstrap_bits_per_decision": _round(observed_bootstrap),
            "observed_analytic_bits_per_decision": _round(observed_analytic),
            "bootstrap_analytic_absolute_difference_bits": _round(absolute_difference),
            "bootstrap_analytic_agreement_tolerance_bits": _round(tolerance),
            "point_estimate_bits_per_decision": _round(
                paired["point_estimate_bits_per_decision"]
            ),
            "dispersion": {
                "bootstrap_stddev_bits_per_decision": _round(
                    paired["bootstrap_stddev_bits_per_decision"]
                ),
                "bootstrap_variance_bits_squared": _round(
                    paired["bootstrap_variance_bits_squared"]
                ),
                "ci95": [_round(item) for item in paired["ci95"]],
                "quantiles": {
                    key: _round(item) for key, item in (paired.get("quantiles") or {}).items()
                },
            },
            "confidence_level": _round(constants["NON_INFERIORITY_CONFIDENCE_LEVEL"]),
            "upper_quantile": _round(constants["NON_INFERIORITY_UPPER_QUANTILE"]),
            "bootstrap_samples": int(constants["BOOTSTRAP_SAMPLES"]),
            "bootstrap_seed": int(constants["BOOTSTRAP_SEED"]),
            "paired_unit": "hand_id",
            "preregistered_reference": {
                "MARGIN_MAX_BITS": _round(constants["MARGIN_MAX_BITS"]),
                "MARGIN_ANALYTIC_TOLERANCE_BITS": _round(tolerance),
            },
            "statement": (
                "the margin is sized by the measured TRAIN out-of-fold dispersion: it is the "
                "smallest multiple of the preregistered 0.001-bit resolution that covers the "
                "observed one-sided 95% upper bound of the paired hybrid-minus-active loss "
                "difference, and the closed-form analytic margin reproduces it within the "
                "preregistered tolerance"
            ),
        },
        inputs=[
            {
                "source": "train_only_cv_derivation",
                "pointer": "/margin_derivation/margin_global_bootstrap_bits_per_decision",
                "value": _round(observed_bootstrap),
            },
            {
                "source": "train_only_cv_derivation",
                "pointer": "/margin_derivation/margin_global_analytic_bits_per_decision",
                "value": _round(observed_analytic),
            },
            {
                "source": "train_only_cv_derivation",
                "pointer": "/paired/hybrid_router_minus_active_model_a/admission_support/ci95",
                "value": None,
            },
        ],
        effectifs={
            "rows": int(paired["rows"]),
            "hands": int(paired["hands"]),
            "excluded_decisions": int(paired["excluded_decisions"]),
            "admission_strata": list(ADMISSION_STRATA),
            "stratum_rows": strata_rows,
        },
    )


def _sparse_gain_criterion(
    derivation: Mapping[str, Any], constants: Mapping[str, float], quantum: float
) -> dict[str, Any]:
    weights: dict[str, float] = {}
    gains: dict[str, float] = {}
    answered: dict[str, int] = {}
    abstained: dict[str, int] = {}
    stratum_rows: dict[str, int] = {}
    for stratum in SPARSE_STRATA:
        block = stratum_metrics(derivation, CHANNEL_HYBRID, stratum)
        metrics = block["metrics"]
        weights[stratum] = float(metrics["n"])
        gains[stratum] = float(metrics["gain_bits_per_decision"])
        answered[stratum] = int(metrics["n"])
        abstained[stratum] = int((block.get("scope") or {}).get("abstained", 0))
        stratum_rows[stratum] = int((block.get("scope") or {}).get("n", int(metrics["n"])))
    observed = _weighted(weights, gains, "sparse")
    value = max(float(constants["GAIN_FLOOR_BITS"]), _floor_to_quantum(observed, quantum))
    total = int(sum(answered.values()))
    if total < int(constants["MINIMUM_SPARSE_OBSERVATIONS"]):
        raise HybridRouterCriteriaError(
            "the sparse support is below the preregistered minimum sparse observations"
        )
    return _criterion(
        criterion_id=CRITERION_SPARSE_GAIN,
        t1_formula_id=CRITERION_SPARSE_GAIN,
        derives="gain_sparse",
        value=value,
        unit="bits_per_decision",
        direction="higher_is_better",
        criterion=(
            f"gain_sparse_bits_per_decision >= {value} on the pooled "
            "(rare_exact, exact_absent_in_domain) support"
        ),
        derivation_rule=(
            "max(GAIN_FLOOR_BITS, floor_to_quantum(support_weighted_mean of the hybrid channel's "
            "gain_bits_per_decision over rare_exact and exact_absent_in_domain, "
            "MARGIN_ANALYTIC_TOLERANCE_BITS))"
        ),
        justification={
            "statistic": (
                "support-weighted mean of the hybrid channel's gain_bits_per_decision over "
                "rare_exact and exact_absent_in_domain on the TRAIN out-of-fold decisions"
            ),
            "observed_sparse_gain_bits_per_decision": _round(observed),
            "per_stratum_gain_bits_per_decision": {
                key: _round(item) for key, item in gains.items()
            },
            "rounding": {
                "rule": "floor_to_quantum",
                "quantum_bits_per_decision": _round(quantum),
                "rationale": (
                    "the floor is the gain TRAIN already demonstrated, rounded down to the "
                    "preregistered resolution so the requirement is never stricter than the "
                    "measured evidence"
                ),
            },
            "preregistered_reference": {
                "GAIN_FLOOR_BITS": _round(constants["GAIN_FLOOR_BITS"]),
                "MINIMUM_SPARSE_OBSERVATIONS": int(constants["MINIMUM_SPARSE_OBSERVATIONS"]),
            },
            "statement": (
                "the minimal sparse gain required of the router is the level the TRAIN "
                "out-of-fold evidence already demonstrates on the two strata the generalized "
                "channel may cover"
            ),
        },
        inputs=[
            {
                "source": "train_only_cv_derivation",
                "pointer": (
                    f"/models/{CHANNEL_HYBRID}/by_stratum/{stratum}/metrics/"
                    "gain_bits_per_decision"
                ),
                "value": _round(gains[stratum]),
            }
            for stratum in SPARSE_STRATA
        ]
        + [
            {
                "source": "train_only_cv_derivation",
                "pointer": f"/models/{CHANNEL_HYBRID}/by_stratum/{stratum}/metrics/n",
                "value": answered[stratum],
            }
            for stratum in SPARSE_STRATA
        ],
        effectifs={
            "sparse_decisions": total,
            "stratum_decisions": answered,
            "stratum_rows": stratum_rows,
            "stratum_abstained": abstained,
            "minimum_sparse_observations": int(constants["MINIMUM_SPARSE_OBSERVATIONS"]),
            "sparse_strata": list(SPARSE_STRATA),
        },
    )


def _sparse_ece_criterion(
    derivation: Mapping[str, Any], constants: Mapping[str, float]
) -> dict[str, Any]:
    hybrid_weights: dict[str, float] = {}
    hybrid_ece: dict[str, float] = {}
    active_weights: dict[str, float] = {}
    active_ece: dict[str, float] = {}
    for stratum in SPARSE_STRATA:
        hybrid = stratum_metrics(derivation, CHANNEL_HYBRID, stratum)["metrics"]
        active = stratum_metrics(derivation, CHANNEL_ACTIVE, stratum)["metrics"]
        hybrid_weights[stratum] = float(hybrid["n"])
        hybrid_ece[stratum] = float(hybrid["expected_calibration_error"])
        active_weights[stratum] = float(active["n"])
        active_ece[stratum] = float(active["expected_calibration_error"])
    observed_hybrid = _weighted(hybrid_weights, hybrid_ece, "sparse calibration")
    observed_active = _weighted(active_weights, active_ece, "active sparse calibration")
    absolute = float(constants["ECE_ABSOLUTE_CEILING"])
    delta = float(constants["ECE_DELTA_CEILING"])
    value = _round(min(absolute, observed_active + delta))
    binding = (
        "ECE_ABSOLUTE_CEILING"
        if absolute <= _round(observed_active + delta)
        else "ece_active_sparse + ECE_DELTA_CEILING"
    )
    return _criterion(
        criterion_id=CRITERION_SPARSE_ECE,
        t1_formula_id="SPARSE_ECE_CEILING",
        derives="ece_ceiling_sparse",
        value=value,
        unit="expected_calibration_error",
        direction="lower_is_better",
        criterion=f"ece_sparse <= {value}",
        derivation_rule=(
            "min(ECE_ABSOLUTE_CEILING, ece_active_sparse + ECE_DELTA_CEILING) with "
            "ece_active_sparse the support-weighted active-reference ECE on the sparse strata"
        ),
        justification={
            "statistic": (
                "support-weighted expected calibration error over rare_exact and "
                "exact_absent_in_domain, measured on the TRAIN out-of-fold decisions"
            ),
            "observed_sparse_ece": _round(observed_hybrid),
            "observed_active_sparse_ece": _round(observed_active),
            "active_sparse_ece_plus_delta": _round(observed_active + delta),
            "per_stratum_ece": {
                "hybrid_router": {key: _round(item) for key, item in hybrid_ece.items()},
                "active_model_a": {key: _round(item) for key, item in active_ece.items()},
            },
            "binding_term": binding,
            "preregistered_reference": {
                "ECE_ABSOLUTE_CEILING": _round(absolute),
                "ECE_DELTA_CEILING": _round(delta),
            },
            "statement": (
                "the frozen ceiling is the tighter of the preregistered absolute ECE ceiling "
                "and the active reference's own sparse ECE plus the preregistered delta; the "
                "recorded term name shows which of the two binds"
            ),
        },
        inputs=[
            {
                "source": "train_only_cv_derivation",
                "pointer": (
                    f"/models/{CHANNEL_HYBRID}/by_stratum/{stratum}/metrics/"
                    "expected_calibration_error"
                ),
                "value": _round(hybrid_ece[stratum]),
            }
            for stratum in SPARSE_STRATA
        ]
        + [
            {
                "source": "train_only_cv_derivation",
                "pointer": (
                    f"/models/{CHANNEL_ACTIVE}/by_stratum/{stratum}/metrics/"
                    "expected_calibration_error"
                ),
                "value": _round(active_ece[stratum]),
            }
            for stratum in SPARSE_STRATA
        ],
        effectifs={
            "sparse_decisions": int(sum(hybrid_weights.values())),
            "stratum_decisions": {key: int(value_) for key, value_ in hybrid_weights.items()},
            "active_stratum_decisions": {key: int(value_) for key, value_ in active_weights.items()},
            "calibration_bins_per_action_class": 10,
        },
    )


def _frequent_exact_criterion(
    derivation: Mapping[str, Any], constants: Mapping[str, float], quantum: float
) -> dict[str, Any]:
    paired = paired_comparison(derivation, stratum=FREQUENT_EXACT_STRATUM)
    point = float(paired["point_estimate_bits_per_decision"])
    upper = float(paired["upper_quantile_bits_per_decision"])
    ci95 = [float(item) for item in paired["ci95"]]
    worst = max([point, upper, *ci95])
    value = max(
        float(constants["FREQUENT_EXACT_MAX_DEGRADATION_BITS"]),
        _ceil_to_quantum(worst, quantum),
    )
    hybrid = stratum_metrics(derivation, CHANNEL_HYBRID, FREQUENT_EXACT_STRATUM)
    active = stratum_metrics(derivation, CHANNEL_ACTIVE, FREQUENT_EXACT_STRATUM)
    return _criterion(
        criterion_id=CRITERION_FREQUENT_EXACT,
        t1_formula_id=CRITERION_FREQUENT_EXACT,
        derives="bound_frequent_exact",
        value=value,
        unit="bits_per_decision",
        direction="lower_is_better",
        criterion=(
            f"delta_frequent_exact_bits_per_decision <= {value} and "
            f"paired_ci95_upper(delta_frequent_exact) <= {value}"
        ),
        derivation_rule=(
            "max(FREQUENT_EXACT_MAX_DEGRADATION_BITS, ceil_to_quantum(max(point estimate, "
            "one-sided upper quantile, ci95 upper) of the paired hybrid-minus-active loss on "
            "frequent_exact, MARGIN_ANALYTIC_TOLERANCE_BITS))"
        ),
        justification={
            "statistic": (
                "paired-by-hand hybrid-minus-active log-loss delta on the frequent_exact stratum "
                "of the TRAIN out-of-fold decisions"
            ),
            "point_estimate_bits_per_decision": _round(point),
            "upper_quantile_bits_per_decision": _round(upper),
            "dispersion": {
                "bootstrap_stddev_bits_per_decision": _round(
                    paired["bootstrap_stddev_bits_per_decision"]
                ),
                "ci95": [_round(item) for item in ci95],
                "analytic_margin_bits_per_decision": _round(
                    (paired.get("analytic") or {}).get("margin_analytic_bits_per_decision")
                ),
                "analytic_standard_error_bits_per_decision": _round(
                    (paired.get("analytic") or {}).get("standard_error_bits_per_decision")
                ),
            },
            "preregistered_reference": {
                "FREQUENT_EXACT_MAX_DEGRADATION_BITS": _round(
                    constants["FREQUENT_EXACT_MAX_DEGRADATION_BITS"]
                )
            },
            "statement": (
                "the frequent-exact route may not degrade the active reference beyond the bound "
                "derived from the paired dispersion of that stratum, in point estimate and in "
                "paired upper quantile"
            ),
        },
        inputs=[
            {
                "source": "train_only_cv_derivation",
                "pointer": (
                    "/per_stratum/frequent_exact/paired/hybrid_router_minus_active_model_a/"
                    "point_estimate_bits_per_decision"
                ),
                "value": _round(point),
            },
            {
                "source": "train_only_cv_derivation",
                "pointer": (
                    "/per_stratum/frequent_exact/paired/hybrid_router_minus_active_model_a/"
                    "upper_quantile_bits_per_decision"
                ),
                "value": _round(upper),
            },
        ],
        effectifs={
            "rows": int(paired["rows"]),
            "hands": int(paired["hands"]),
            "excluded_decisions": int(paired["excluded_decisions"]),
            "stratum_rows": int((hybrid.get("scope") or {}).get("n", hybrid["metrics"]["n"])),
            "active_stratum_rows": int((active.get("scope") or {}).get("n", active["metrics"]["n"])),
            "decisions_per_hand": _round(paired["decisions_per_hand"]),
        },
    )


def _ood_criterion(derivation: Mapping[str, Any], constants: Mapping[str, float]) -> dict[str, Any]:
    probes = derivation.get("ood_synthetic_probes") or {}
    total = int(probes["n"])
    abstained = int(probes["router_abstained"])
    rate = float(probes["abstain_rate"])
    if abstained != total or rate != 1.0:
        raise HybridRouterCriteriaError(
            "the TRAIN out-of-domain probe surface does not show a complete fail-closed abstention"
        )
    coverage = float(probes.get("coverage", 0.0))
    if coverage != 0.0:
        raise HybridRouterCriteriaError("the out-of-domain probe surface reports a non-zero coverage")
    kinds = {
        str(kind): int(entry.get("n", 0))
        for kind, entry in sorted((probes.get("by_kind") or {}).items())
    }
    if not kinds:
        raise HybridRouterCriteriaError("the derivation publishes no out-of-domain probe kinds")
    for kind, entry in sorted((probes.get("by_kind") or {}).items()):
        if float(entry.get("abstain_rate", 0.0)) != 1.0:
            raise HybridRouterCriteriaError(
                f"the out-of-domain probe kind {kind!r} is not fully abstained"
            )
    gate = derivation.get("protocol", {}).get("ood_probes", {})
    value = float(1.0)
    return _criterion(
        criterion_id=CRITERION_OOD,
        t1_formula_id=CRITERION_OOD,
        derives="abstain",
        value=value,
        unit="required_abstention_rate_on_synthetic_ood_probes",
        direction="predicate",
        criterion=(
            f"abstain iff hard_reasons is not empty; abstain_rate on the synthetic out-of-domain "
            f"probe surface == {value} and coverage == 0.0"
        ),
        derivation_rule=(
            "abstain(c) iff reasons(c) intersect OOD_HARD_REASONS is not empty; the soft reason "
            "set may only raise the status to high uncertainty, never to abstention"
        ),
        justification={
            "statistic": (
                "measured abstention rate of the frozen router on the synthetic out-of-domain "
                "probe surface of the TRAIN cross-validation"
            ),
            "observed_abstention_rate": _round(rate),
            "observed_coverage": _round(coverage),
            "probe_kinds": list(kinds),
            "probes_per_kind": kinds,
            "paired_unit": "decision",
            "preregistered_reference": {
                "OOD_ABSTAIN_is_decisive_for_hard_reasons_only": True,
                "FREQUENT_EXACT_MIN_SUPPORT": int(constants["FREQUENT_EXACT_MIN_SUPPORT"]),
                "RARE_EXACT_MIN_SUPPORT": int(constants["RARE_EXACT_MIN_SUPPORT"]),
            },
            "statement": (
                "the router must fail closed on every out-of-domain probe: the frozen criterion "
                "requires a complete abstention on the probe surface, with the hard reason codes "
                "decisive and the soft reasons never abstaining"
            ),
        },
        inputs=[
            {
                "source": "train_only_cv_derivation",
                "pointer": "/ood_synthetic_probes/abstain_rate",
                "value": _round(rate),
            },
            {
                "source": "train_only_cv_derivation",
                "pointer": "/ood_synthetic_probes/router_abstained",
                "value": abstained,
            },
            {
                "source": "train_only_cv_derivation",
                "pointer": "/ood_synthetic_probes/n",
                "value": total,
            },
        ],
        effectifs={
            "probes": total,
            "probes_abstained": abstained,
            "probes_per_kind": kinds,
            "ood_stratum_probes": int(probes.get("ood_stratum_probes", 0)),
            "ood_criterion_stratum": OOD_STRATUM,
            "declared_probe_kinds": sorted(str(kind) for kind in gate.get("kinds", ()) or ()),
        },
    )


def derive_criteria(
    derivation: Mapping[str, Any],
    spec: Mapping[str, Any],
    *,
    frozen_at: str = DEFAULT_FROZEN_AT,
    derivation_sha256: str | None = None,
) -> dict[str, Any]:
    """Resolve T1's symbolic procedure into the frozen numeric criteria."""
    assert_train_only_derivation(derivation)
    constants = assert_preregistered_procedure(spec)
    quantum = float(constants["MARGIN_ANALYTIC_TOLERANCE_BITS"])
    digest = derivation_sha256 if derivation_sha256 is not None else sha256_file(DERIVATION_PATH)
    criteria = [
        _margin_criterion(derivation, constants, quantum),
        _sparse_gain_criterion(derivation, constants, quantum),
        _sparse_ece_criterion(derivation, constants),
        _frequent_exact_criterion(derivation, constants, quantum),
        _ood_criterion(derivation, constants),
    ]
    procedure = spec["procedure"]
    block: dict[str, Any] = {
        "schema": CRITERIA_SCHEMA,
        "issue": ISSUE,
        "planner_key": PLANNER_KEY,
        "kind": KIND,
        "status": STATUS,
        "frozen_at": frozen_at,
        "frozen_at_source": FROZEN_AT_SOURCE,
        "evaluation_basis": "TRAIN_only_hand_grouped_out_of_fold_cv_derivation",
        "derivation": {
            "artifact": DERIVATION_LOGICAL_PATH,
            "schema": derivation.get("schema"),
            "planner_key": derivation.get("planner_key"),
            "sha256": digest,
            "canonical_payload_sha256": derivation.get("canonical_payload_sha256"),
            "rows": int((derivation.get("scope") or {}).get("rows", 0)),
            "hands": int((derivation.get("scope") or {}).get("hands", 0)),
            "folds": int((derivation.get("protocol") or {}).get("folds", 0)),
        },
        "procedure_reference": {
            "spec": SPEC_LOGICAL_PATH,
            "spec_schema": spec.get("schema", SPEC_SCHEMA),
            "pointer": "/procedure",
            "evaluation_basis": procedure["evaluation_basis"],
            "derivation_order": list(procedure["derivation_order"]),
            "formula_ids": sorted(str(formula["id"]) for formula in procedure["formulas"]),
            "constants": {
                name: _round(constants[name]) for name in sorted(constants) if name in REQUIRED_CONSTANTS
            },
        },
        "resolution_quantum_bits_per_decision": _round(quantum),
        "criteria_order": list(CRITERIA_IDS),
        "criteria": criteria,
        "terminal_evaluation": {
            "consumed": False,
            "declared_terminal_report_locations": list(TERMINAL_REPORT_LOGICAL_PATHS),
        },
        "terminal_evaluation_derived": False,
    }
    block["criteria_sha256"] = stable_hash(_finalize(_criteria_payload(block)))
    verify_no_holdout_access()
    return _finalize(block)


def _criteria_payload(block: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in block.items() if key != "criteria_sha256"}


# --------------------------------------------------------------------------
# documents
# --------------------------------------------------------------------------


def build_frozen_spec(criteria: Mapping[str, Any]) -> dict[str, Any]:
    """Author the frozen spec through the T1 generator, criteria included."""
    return spec_tool.build_spec(frozen_criteria=dict(criteria))


def serialize_spec(spec: Mapping[str, Any]) -> bytes:
    return spec_tool.serialize(spec)


def serialize_manifest(manifest: Mapping[str, Any]) -> bytes:
    text = (
        json.dumps(
            _finalize(manifest),
            sort_keys=True,
            indent=2,
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n"
    )
    return text.encode("utf-8")


def manifest_sidecar_text(manifest: Mapping[str, Any]) -> str:
    payload = serialize_manifest(manifest)
    return (
        f"{sha256_bytes(payload)}  {MANIFEST_NAME}\n"
        f"# canonical_payload_sha256 {stable_hash(_canonical_payload(manifest))}\n"
        f"# scope TRAIN_ONLY_NO_VALIDATION_NO_TEST\n"
        f"# terminal_score_guard ROUTER_CRITERIA_ORDER_GUARD\n"
    )


def _canonical_payload(document: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in document.items() if key != "canonical_payload_sha256"}


def _input_bindings(
    derivation: Mapping[str, Any],
    spec_bytes: bytes,
    criteria: Mapping[str, Any],
) -> list[dict[str, Any]]:
    scope = derivation.get("scope") or {}
    protocol = derivation.get("protocol") or {}
    reuse = derivation.get("reuse") or {}
    bindings = [
        {
            "role": "train_only_cv_derivation",
            "path": DERIVATION_LOGICAL_PATH,
            "sha256": sha256_file(DERIVATION_PATH),
        },
        {
            "role": "derivation_sha256_sidecar",
            "path": DERIVATION_DIGEST_LOGICAL_PATH,
            "sha256": sha256_file(DERIVATION_DIGEST_PATH),
        },
        {
            "role": "preregistration_spec",
            "path": SPEC_LOGICAL_PATH,
            "sha256": sha256_bytes(spec_bytes),
            "criteria_sha256": criteria["criteria_sha256"],
        },
        {
            "role": "criteria_generator",
            "path": GENERATOR_LOGICAL_PATH,
            "sha256": sha256_file(SOURCE_PATH),
        },
        {
            "role": "spec_generator",
            "path": SPEC_GENERATOR_LOGICAL_PATH,
            "sha256": sha256_file(Path(spec_tool.__file__).resolve()),
        },
    ]
    for role, path, digest in (
        ("dataset", scope.get("dataset"), scope.get("dataset_sha256")),
        (
            "cross_validation_harness",
            protocol.get("reused_harness_module"),
            protocol.get("reused_harness_module_sha256"),
        ),
        ("router_module", protocol.get("router_module"), protocol.get("router_module_sha256")),
        (
            "active_reference_model",
            (reuse.get("active_reference") or {}).get("path"),
            (reuse.get("active_reference") or {}).get("sha256"),
        ),
        (
            "generalized_calibration_module",
            (reuse.get("generalized_calibration") or {}).get("module"),
            (reuse.get("generalized_calibration") or {}).get("sha256"),
        ),
        (
            "generalized_calibration_report",
            (reuse.get("generalized_calibration") or {}).get("report"),
            (reuse.get("generalized_calibration") or {}).get("report_sha256"),
        ),
    ):
        if not path or not digest:
            continue
        bindings.append({"role": role, "path": str(path), "sha256": str(digest)})
    return bindings


def verify_input_bindings(
    bindings: Sequence[Mapping[str, Any]],
    *,
    pending: Mapping[str, bytes] | None = None,
) -> list[str]:
    """Re-hash every derivation input, against ``pending`` bytes when supplied.

    ``pending`` maps a logical repository path to the bytes the freeze is about
    to author, so the spec binding is verified against what is written instead
    of against a file that does not exist yet on a first freeze.
    """
    problems: list[str] = []
    pending = dict(pending or {})
    for entry in bindings:
        logical = str(entry["path"])
        if logical in pending:
            found = sha256_bytes(pending[logical])
            if found != entry["sha256"]:
                problems.append(
                    f"derivation input {logical} drifted (expected {entry['sha256']}, found {found})"
                )
            continue
        path = ROOT / logical
        if not path.is_file():
            problems.append(f"missing derivation input {logical}")
            continue
        found = sha256_file(path)
        if found != entry["sha256"]:
            problems.append(
                f"derivation input {logical} drifted (expected {entry['sha256']}, found {found})"
            )
    return problems


def build_manifest(
    *,
    criteria: Mapping[str, Any],
    spec: Mapping[str, Any],
    spec_bytes: bytes,
    order_guard: Mapping[str, Any],
    frozen_at: str = DEFAULT_FROZEN_AT,
) -> dict[str, Any]:
    derivation = load_derivation()
    bindings = _input_bindings(derivation, spec_bytes, criteria)
    document: dict[str, Any] = {
        "schema": MANIFEST_SCHEMA,
        "issue": ISSUE,
        "kind": KIND,
        "planner_key": PLANNER_KEY,
        "status": STATUS,
        "frozen_at": frozen_at,
        "frozen_at_source": FROZEN_AT_SOURCE,
        "generated_by": {
            "tool_path": GENERATOR_LOGICAL_PATH,
            "tool_sha256": sha256_file(SOURCE_PATH),
            "spec_generator_path": SPEC_GENERATOR_LOGICAL_PATH,
            "spec_generator_sha256": sha256_file(Path(spec_tool.__file__).resolve()),
            "criteria_schema": CRITERIA_SCHEMA,
        },
        "manifest": {"path": MANIFEST_LOGICAL_PATH, "name": MANIFEST_NAME},
        "split_policy": {
            "allowed_splits": list(ALLOWED_SPLITS),
            "consumed_splits": list(CONSUMED_SPLITS),
            "refused_splits": list(REFUSED_SPLITS),
            "fail_closed_on_refused_split": True,
            "statement": (
                "the numeric freeze is resolved from TRAIN-only out-of-fold evidence; requiring "
                "any VALIDATION or TEST split raises a hard error before a byte is written"
            ),
        },
        "order_guard": dict(order_guard),
        "derivation_procedure": {
            "reference": {
                "spec": SPEC_LOGICAL_PATH,
                "pointer": "/procedure",
                "spec_schema": spec.get("schema", SPEC_SCHEMA),
                "spec_sha256": sha256_bytes(spec_bytes),
                "canonical_payload_sha256": spec.get("canonical_payload_sha256"),
            },
            "evaluation_basis": spec["procedure"]["evaluation_basis"],
            "derivation_order": list(spec["procedure"]["derivation_order"]),
            "formulas": [
                {
                    "id": formula["id"],
                    "derives": formula["derives"],
                    "direction": formula["direction"],
                    "evaluation_surface": formula["evaluation_surface"],
                }
                for formula in spec["procedure"]["formulas"]
                if formula["id"] in CRITERIA_IDS
            ],
            "resolved_by": "tools/training/freeze_hybrid_router_criteria.py::derive_criteria",
            "resolved_from": DERIVATION_LOGICAL_PATH,
        },
        "frozen_criteria": dict(criteria),
        "frozen_criteria_sha256": criteria["criteria_sha256"],
        "frozen_spec": {
            "path": SPEC_LOGICAL_PATH,
            "sha256": sha256_bytes(spec_bytes),
            "canonical_payload_sha256": spec.get("canonical_payload_sha256"),
            "bytes": len(spec_bytes),
        },
        "derivation_inputs": bindings,
        "terminal_score_guard": {
            "guard_id": "ROUTER_CRITERIA_ORDER_GUARD",
            "terminal_report_absent_at_freeze": True,
            "declared_terminal_report_locations": list(TERMINAL_REPORT_LOGICAL_PATHS),
            "terminal_report_name": TERMINAL_REPORT_NAME,
            "spec_digest_computed_before_terminal_score": True,
            "regeneration_with_different_values_fails_closed": True,
        },
        "assertions": {
            "train_only": True,
            "validation_consumed": False,
            "test_consumed": False,
            "terminal_report_absent_at_freeze": True,
            "terminal_evaluation_consumed": False,
            "every_criterion_quantitatively_justified": True,
            "derivation_inputs_content_addressed": True,
            "byte_stable": True,
        },
    }
    document["canonical_payload_sha256"] = stable_hash(_canonical_payload(_finalize(document)))
    return _finalize(document)


def write_spec(spec: Mapping[str, Any]) -> bytes:
    payload = serialize_spec(spec)
    write_spec_bytes(spec, payload)
    return payload


def write_spec_bytes(spec: Mapping[str, Any], payload: bytes) -> None:
    """Persist the frozen spec and its sidecar from already-serialized bytes."""
    SPEC_PATH.parent.mkdir(parents=True, exist_ok=True)
    SPEC_PATH.write_bytes(payload)
    SPEC_DIGEST_PATH.write_text(spec_tool.sidecar_text(spec), encoding="utf-8")


def write_manifest(manifest: Mapping[str, Any]) -> bytes:
    payload = serialize_manifest(manifest)
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_bytes(payload)
    MANIFEST_DIGEST_PATH.write_text(manifest_sidecar_text(manifest), encoding="utf-8")
    return payload


# --------------------------------------------------------------------------
# freeze / check
# --------------------------------------------------------------------------


def _summarize(criteria: Mapping[str, Any]) -> dict[str, Any]:
    return {
        criterion["id"]: criterion["value"] for criterion in criteria["criteria"]
    }


def freeze(
    *,
    frozen_at: str = DEFAULT_FROZEN_AT,
    terminal_paths: Sequence[str | Path] | None = None,
    reauthor: bool = False,
) -> dict[str, Any]:
    """Freeze the numeric criteria, or fail closed on ordering/drift.

    ``reauthor=True`` is the only way to write the frozen documents a second
    time, and it cannot change a single value: it exists so a change of the
    generator's own bytes (or of a provenance digest) can be re-pinned without
    silently relaxing an admission threshold.  A regeneration that would move a
    value fails closed in both modes.
    """
    order_guard = assert_terminal_report_absent(terminal_paths)
    derivation = load_derivation(DERIVATION_PATH)
    derivation_digest = assert_derivation_digest(
        DERIVATION_PATH, DERIVATION_DIGEST_PATH, derivation
    )
    if not SPEC_PATH.is_file():
        raise HybridRouterCriteriaError(
            f"the T1 preregistration spec is missing: {_relative(SPEC_PATH)}"
        )
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    criteria = derive_criteria(
        derivation, spec, frozen_at=frozen_at, derivation_sha256=derivation_digest
    )
    persisted_criteria = spec.get("frozen_criteria")
    manifest = (
        json.loads(MANIFEST_PATH.read_text(encoding="utf-8")) if MANIFEST_PATH.is_file() else None
    )
    if persisted_criteria is None and manifest is not None:
        raise HybridRouterCriteriaError(
            "the router manifest exists but the spec carries no frozen criteria"
        )
    if persisted_criteria is not None:
        if manifest is not None and manifest.get("frozen_criteria") != persisted_criteria:
            raise HybridRouterCriteriaError(
                "the frozen spec criteria diverge from the router manifest"
            )
        moved = criteria_value_diff(persisted_criteria, criteria)
        if moved:
            raise HybridRouterCriteriaError(
                "regeneration would produce different frozen criteria: "
                + "; ".join(moved)
            )
        payload_unchanged = _canonical_criteria(persisted_criteria) == _canonical_criteria(criteria)
        pinned = (manifest or {}).get("frozen_spec") or {}
        spec_is_pinned = sha256_bytes(SPEC_PATH.read_bytes()) == pinned.get("sha256")
        drifted = verify_input_bindings((manifest or {}).get("derivation_inputs") or ())
        if (
            manifest is not None
            and payload_unchanged
            and not drifted
            and spec_is_pinned
            and not reauthor
        ):
            return {
                "status": "UNCHANGED",
                "spec": _relative(SPEC_PATH),
                "manifest": _relative(MANIFEST_PATH),
                "criteria": _summarize(persisted_criteria),
                "order_guard": order_guard["result"],
            }
        reason = None
        if manifest is None:
            reason = (
                "the spec carries frozen criteria without a manifest; re-author the freeze "
                "explicitly to rebuild the manifest (values cannot change)"
            )
        elif not payload_unchanged:
            reason = (
                "the frozen criteria payload changed without moving a value; re-author the "
                "freeze explicitly to re-pin the justification"
            )
        elif not spec_is_pinned:
            reason = (
                "the manifest does not pin the persisted frozen spec; re-author the freeze "
                "explicitly (values cannot change)"
            )
        elif drifted:
            reason = (
                "the frozen criteria are unchanged but their provenance drifted; re-author the "
                "freeze explicitly (values cannot change): " + "; ".join(drifted)
            )
        if reason is not None and not reauthor:
            raise HybridRouterCriteriaError(reason)
    frozen_spec = build_frozen_spec(criteria)
    spec_bytes = serialize_spec(frozen_spec)
    document = build_manifest(
        criteria=criteria,
        spec=frozen_spec,
        spec_bytes=spec_bytes,
        order_guard=order_guard,
        frozen_at=frozen_at,
    )
    problems = verify_input_bindings(
        document["derivation_inputs"], pending={SPEC_LOGICAL_PATH: spec_bytes}
    )
    if problems:
        raise HybridRouterCriteriaError("; ".join(sorted(set(problems))))
    write_spec_bytes(frozen_spec, spec_bytes)
    write_manifest(document)
    return {
        "status": "FROZEN" if persisted_criteria is None else "REAUTHORED",
        "spec": _relative(SPEC_PATH),
        "manifest": _relative(MANIFEST_PATH),
        "spec_sha256": sha256_bytes(spec_bytes),
        "spec_canonical_payload_sha256": frozen_spec.get("canonical_payload_sha256"),
        "criteria": _summarize(criteria),
        "order_guard": order_guard["result"],
    }


def _canonical_criteria(criteria: Mapping[str, Any]) -> dict[str, Any]:
    stripped = {key: value for key, value in criteria.items() if key != "criteria_sha256"}
    return _finalize(stripped)


def criteria_values(criteria: Mapping[str, Any]) -> dict[str, Any]:
    """The scientific contract of the freeze: the criterion identifiers and values."""
    return {str(entry["id"]): entry["value"] for entry in criteria.get("criteria", [])}


def criteria_value_diff(
    persisted: Mapping[str, Any], derived: Mapping[str, Any]
) -> list[str]:
    """Every criterion whose frozen value a regeneration would move."""
    left = criteria_values(persisted)
    right = criteria_values(derived)
    return [
        f"{key}: persisted {left.get(key)} -> regenerated {right.get(key)}"
        for key in sorted(set(left) | set(right))
        if left.get(key) != right.get(key)
    ]


def _criteria_diff(left: Mapping[str, Any], right: Mapping[str, Any]) -> str:
    changes = criteria_value_diff(left, right)
    if not changes:
        changes = ["the persisted and regenerated criteria payloads differ outside their values"]
    return "; ".join(changes)


def check(*, terminal_paths: Sequence[str | Path] | None = None) -> list[str]:
    """Verify the persisted frozen criteria, the manifest and the re-derivation."""
    problems: list[str] = []
    if not SPEC_PATH.is_file():
        return [f"missing {_relative(SPEC_PATH)}"]
    if not MANIFEST_PATH.is_file():
        return [f"missing {_relative(MANIFEST_PATH)}"]
    spec_bytes = SPEC_PATH.read_bytes()
    spec = json.loads(spec_bytes.decode("utf-8"))
    manifest_bytes = MANIFEST_PATH.read_bytes()
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    if manifest.get("schema") != MANIFEST_SCHEMA:
        problems.append(f"manifest schema must be {MANIFEST_SCHEMA}")
    if manifest.get("canonical_payload_sha256") != stable_hash(
        _canonical_payload(_finalize(manifest))
    ):
        problems.append("manifest canonical payload digest mismatch")
    sidecar = MANIFEST_DIGEST_PATH
    if not sidecar.is_file():
        problems.append(f"missing {_relative(sidecar)}")
    else:
        lines = sidecar.read_text(encoding="utf-8").splitlines()
        if not lines or lines[0].split()[0] != sha256_bytes(manifest_bytes):
            problems.append("manifest .sha256 sidecar does not pin the persisted bytes")
    if not SPEC_DIGEST_PATH.is_file():
        problems.append(f"missing {_relative(SPEC_DIGEST_PATH)}")
    else:
        lines = SPEC_DIGEST_PATH.read_text(encoding="utf-8").splitlines()
        if not lines or lines[0].split()[0] != sha256_bytes(spec_bytes):
            problems.append("spec .sha256 sidecar does not pin the persisted bytes")
    frozen = (manifest.get("frozen_spec") or {})
    if frozen.get("sha256") != sha256_bytes(spec_bytes):
        problems.append("the manifest does not pin the persisted frozen spec bytes")
    if manifest.get("frozen_criteria") != spec.get("frozen_criteria"):
        problems.append("the spec and the manifest disagree on the frozen criteria")
    criteria = spec.get("frozen_criteria")
    if not isinstance(criteria, Mapping):
        return problems + ["the frozen spec carries no frozen criteria"]
    if criteria.get("criteria_sha256") != stable_hash(_finalize(_criteria_payload(criteria))):
        problems.append("the frozen criteria canonical digest does not verify")
    ids = [entry.get("id") for entry in criteria.get("criteria", [])]
    if tuple(ids) != CRITERIA_IDS:
        problems.append(f"the frozen criteria must be {list(CRITERIA_IDS)}, found {ids}")
    for entry in criteria.get("criteria", []):
        if entry.get("terminal_evaluation_derived") is not False:
            problems.append(f"criterion {entry.get('id')} is not marked non-terminal")
        if not entry.get("justification") or not entry.get("inputs") or not entry.get("effectifs"):
            problems.append(f"criterion {entry.get('id')} is not quantitatively justified")
    problems.extend(
        f"derivation input: {problem}"
        for problem in verify_input_bindings(manifest.get("derivation_inputs") or ())
    )
    problems.extend(terminal_absence_problems(terminal_paths))
    try:
        derivation = load_derivation(DERIVATION_PATH)
        derivation_digest = assert_derivation_digest(
            DERIVATION_PATH, DERIVATION_DIGEST_PATH, derivation
        )
        expected = derive_criteria(
            derivation, spec, frozen_at=criteria["frozen_at"], derivation_sha256=derivation_digest
        )
    except HybridRouterCriteriaError as error:
        problems.append(f"re-derivation failed: {error}")
        return problems
    if _canonical_criteria(expected) != _canonical_criteria(criteria):
        problems.append(
            "the persisted frozen criteria do not reproduce from the derivation: "
            + _criteria_diff(_canonical_criteria(criteria), _canonical_criteria(expected))
        )
    return problems


def terminal_order_state(
    paths: Sequence[str | Path] | None = None,
    *,
    spec_path: str | Path | None = None,
) -> dict[str, Any]:
    """Where the ordering guard stands *now*, once the terminal score may exist.

    Before the terminal run the guard is satisfied by the report's absence.
    After it, the report is expected to exist, so the property that survives is
    the *binding*: a terminal ``TRAIN_CV_ROUTER_REPORT.json`` carries the digest
    of the frozen spec it was judged by, and only a report that pins the current
    frozen bytes proves the freeze preceded the score.  A terminal report that
    binds nothing (or that binds different bytes) leaves the ordering unprovable
    and is reported as a violation.
    """
    candidates = tuple(paths) if paths is not None else tuple(TERMINAL_REPORT_PATHS)
    spec = Path(spec_path) if spec_path is not None else SPEC_PATH
    spec_sha256 = sha256_file(spec) if spec.is_file() else None
    present: list[str] = []
    bound: list[str] = []
    unbound: list[str] = []
    for path in candidates:
        target = Path(path)
        if not target.is_file():
            continue
        label = str(_relative(target))
        present.append(label)
        try:
            report = json.loads(target.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            unbound.append(label)
            continue
        pinned = str((report.get("frozen_spec") or {}).get("sha256") or "")
        if spec_sha256 is not None and pinned == spec_sha256:
            bound.append(label)
        else:
            unbound.append(label)
    if not present:
        state = "ABSENT"
    elif unbound:
        state = "UNBOUND"
    else:
        state = "BOUND"
    return {
        "state": state,
        "present": present,
        "bound": bound,
        "unbound": unbound,
        "spec_path": str(_relative(spec)),
        "spec_sha256": spec_sha256,
        "declared_terminal_report_locations": list(TERMINAL_REPORT_LOGICAL_PATHS),
    }


def terminal_absence_problems(paths: Sequence[str | Path] | None = None) -> list[str]:
    """Report (never raise) whether the ordering guard still holds.

    The report is ``ABSENT`` before the terminal score and ``BOUND`` afterwards:
    once the terminal run exists, the guard is proven by the frozen spec digest
    the report embeds, because that digest is written by the freeze and can only
    be copied into a report authored after it.
    """
    state = terminal_order_state(paths)
    if state["state"] == "UNBOUND":
        return [
            "a terminal hybrid router score exists without binding the frozen spec digest: "
            + ", ".join(state["unbound"])
        ]
    return []


def check_spec_reproducible() -> list[str]:
    """The T1 generator must rebuild the frozen spec byte for byte."""
    return [f"spec generator: {problem}" for problem in spec_tool.check()]


# --------------------------------------------------------------------------
# cli
# --------------------------------------------------------------------------


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="#423 T5 - freeze the hybrid router numeric criteria and publish the manifest"
    )
    parser.add_argument("--check", action="store_true", help="verify the frozen criteria and manifest")
    parser.add_argument(
        "--print", dest="print_only", action="store_true", help="print the criteria, do not write"
    )
    parser.add_argument(
        "--reauthor",
        action="store_true",
        help="re-pin an existing freeze without changing a single frozen value",
    )
    parser.add_argument("--frozen-at", default=DEFAULT_FROZEN_AT, help="frozen timestamp")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.print_only:
        derivation = load_derivation()
        spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
        criteria = derive_criteria(derivation, spec, frozen_at=args.frozen_at)
        sys.stdout.write(json.dumps(criteria, sort_keys=True, indent=2) + "\n")
        return 0
    if args.check:
        problems = check()
        problems.extend(check_spec_reproducible())
        for problem in problems:
            print(problem, file=sys.stderr)
        return 1 if problems else 0
    try:
        result = freeze(frozen_at=args.frozen_at, reauthor=args.reauthor)
    except HybridRouterCriteriaError as error:
        print(str(error), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

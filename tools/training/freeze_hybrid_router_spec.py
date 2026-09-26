#!/usr/bin/env python3
"""#423 T1 - freeze the hybrid router spec and its pre-registration procedure.

Writes ``analysis/issue423_hybrid_router/HYBRID_ROUTER_SPEC.json`` plus a
``HYBRID_ROUTER_SPEC.sha256`` sidecar.  The document declares, machine-readable
and *before* any closure evaluation:

* the three route sources ``ACTIVE_STRONG_SUPPORT`` /
  ``GENERALIZED_SPARSE_IN_DOMAIN`` / ``OOD_ABSTAIN`` and the ordered decision
  table that selects between them;
* the stable pre-action signals the route decision may read (exact and
  feature-level support, robust domain distance, predictive uncertainty, the
  sizing / stack / price extrapolations, and the family / position blocks only
  where the TRAIN out-of-fold evidence justifies them);
* the reason-code catalog reused verbatim from #421's OOD gate;
* the runtime contract a routed answer must satisfy (``route_source``,
  ``model_id`` / ``model_hash``, ``support_state``, ``uncertainty``,
  ``ood_status``, ``probabilities``, the sizing provenance required on
  ``RAISE`` / ``JAM`` and ``analysis_admissible``);
* the exact procedure that derives the **global non-inferiority margin**, the
  **sparse gain floor** (``rare_exact`` + ``exact_absent_in_domain``), the
  **sparse ECE ceiling**, the **frequent-exact non-degradation bound** and the
  **OOD abstention criterion**.

Scientific boundary
-------------------
The spec is authored and hashed from TRAIN-only out-of-fold evidence and from
preregistered constants, never from a terminal evaluation.  This tool has no
holdout code path: it parses no hand history and no decision JSONL, it consumes
the frozen #421 TRAIN cross-validation report as a content-addressed artifact,
it fails closed when a consumed split is not ``TRAIN``, and it statically
refuses to name a holdout loader (see :func:`verify_no_holdout_access`).  The
persisted document therefore carries no numeric value issued from a VALIDATION
or TEST evaluation; the formulas whose inputs only exist on the future frozen
admission support are declared as *procedures*, not as results.

Only the Python standard library is used.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SOURCE_PATH = Path(__file__).resolve()

from tools.preflop import generalized_response_model as grm  # noqa: E402
from tools.training import evaluate_generalized_response_cv as cv  # noqa: E402

# --------------------------------------------------------------------------
# layout and identity
# --------------------------------------------------------------------------

HERE = ROOT / "analysis/issue423_hybrid_router"
SPEC_NAME = "HYBRID_ROUTER_SPEC.json"
SPEC_PATH = HERE / SPEC_NAME
DIGEST_PATH = HERE / "HYBRID_ROUTER_SPEC.sha256"

SCHEMA_PATH = ROOT / "contracts/training/hybrid-router-spec.schema.json"
CV_REPORT_PATH = ROOT / "analysis/issue421_generalized_response/TRAIN_CV_REPORT.json"
OOD_GATE_SCHEMA_PATH = ROOT / "contracts/training/generalized-response-ood-gate.schema.json"
MODEL_MODULE_PATH = ROOT / "tools/preflop/generalized_response_model.py"
CV_MODULE_PATH = ROOT / "tools/training/evaluate_generalized_response_cv.py"

SPEC_SCHEMA = "poker-hybrid-router-spec/v1"
ISSUE = 423
KIND = "hybrid_router_spec_and_preregistration_procedure"
STATUS = "SPEC_ONLY_PREREGISTERED_NOT_ADMITTED"
RUNTIME_CONTRACT_SCHEMA = "poker-hybrid-router-runtime-contract/v1"

#: The freeze consumes exactly one split; the two holdouts are refused.
ALLOWED_SPLITS = ("TRAIN",)
CONSUMED_SPLITS = ("TRAIN",)
REFUSED_SPLITS = ("VALIDATION", "TEST")

#: Logical (repository-relative) paths serialized into the frozen document, so
#: a rebuild in another layout reproduces the same bytes.
CV_REPORT_LOGICAL_PATH = "analysis/issue421_generalized_response/TRAIN_CV_REPORT.json"
OOD_GATE_SCHEMA_LOGICAL_PATH = "contracts/training/generalized-response-ood-gate.schema.json"
MODEL_MODULE_LOGICAL_PATH = "tools/preflop/generalized_response_model.py"
CV_MODULE_LOGICAL_PATH = "tools/training/evaluate_generalized_response_cv.py"
GENERATOR_LOGICAL_PATH = "tools/training/freeze_hybrid_router_spec.py"

#: Symbols that would indicate a holdout (VALIDATION/TEST) read.  The generator
#: must use none of them; the scan runs at build time and in tests.
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


class HybridRouterSpecError(RuntimeError):
    """Fail-closed error for the hybrid router spec surface."""


# --------------------------------------------------------------------------
# small helpers
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
    """Canonical payload digest: sorted keys, no insignificant whitespace."""
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(raw).hexdigest()


def _relative(path: str | Path) -> str:
    resolved = Path(path).resolve()
    try:
        return str(resolved.relative_to(ROOT))
    except ValueError:
        return str(resolved)


def verify_no_holdout_access(source: str | None = None) -> dict[str, Any]:
    """Static, reproducible proof that the generator cannot read a holdout split.

    The scan is AST-based on purpose: it looks for identifiers actually used
    (calls, attribute access, imports) and for holdout-looking data paths, not
    for the words themselves, so the declarative constants above stay readable.
    """
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
        raise HybridRouterSpecError(f"holdout loader symbol used in spec generator: {hits}")
    bad_imports = sorted(
        name for name in imported if any(marker in name.lower() for marker in ("validation", "holdout"))
    )
    if bad_imports:
        raise HybridRouterSpecError(f"holdout-looking import in spec generator: {bad_imports}")
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
        raise HybridRouterSpecError(f"holdout-looking data path literal: {bad_literals}")
    return {
        "check": "self_source_scan_for_holdout_loaders",
        "result": "PASS",
        "forbidden_symbols": list(HOLDOUT_LOADER_SYMBOLS),
        "hits": [],
        "holdout_looking_imports": [],
        "holdout_looking_data_path_literals": [],
        "detail": (
            "AST scan: the spec generator uses none of the forbidden holdout loader symbols, imports "
            "no validation/holdout module and declares no validation/holdout data path"
        ),
    }


# --------------------------------------------------------------------------
# TRAIN-only evidence
# --------------------------------------------------------------------------


def assert_allowed_splits(splits: Sequence[str]) -> tuple[str, ...]:
    """Fail closed when a split outside :data:`ALLOWED_SPLITS` is required."""
    resolved = tuple(str(split).strip().upper() for split in splits)
    if not resolved:
        raise HybridRouterSpecError("the freeze must consume exactly the TRAIN split")
    refused = sorted({split for split in resolved if split not in ALLOWED_SPLITS})
    if refused:
        raise HybridRouterSpecError(
            f"refused split(s) required by the hybrid router freeze: {refused}; "
            f"only {list(ALLOWED_SPLITS)} may be consumed"
        )
    if tuple(sorted(resolved)) != tuple(sorted(CONSUMED_SPLITS)):
        raise HybridRouterSpecError(
            f"consumed splits {list(resolved)} diverge from the frozen {list(CONSUMED_SPLITS)}"
        )
    return resolved


def load_train_cv_report(path: str | Path | None = None) -> dict[str, Any]:
    source = Path(path) if path is not None else CV_REPORT_PATH
    return json.loads(source.read_text(encoding="utf-8"))


def assert_train_only_report(report: Mapping[str, Any]) -> None:
    scope = report.get("scope") or {}
    consumed = tuple(str(split).upper() for split in (scope.get("consumed_splits") or ()))
    if consumed and consumed != tuple(ALLOWED_SPLITS):
        raise HybridRouterSpecError(
            f"the TRAIN cross-validation report declares consumed splits {list(consumed)}; "
            "the hybrid router freeze only accepts a TRAIN-only report"
        )
    if bool(scope.get("validation_consumed")):
        raise HybridRouterSpecError("the consumed cross-validation report read VALIDATION")
    if bool(scope.get("test_consumed")):
        raise HybridRouterSpecError("the consumed cross-validation report read TEST")
    selection = report.get("selection") or {}
    if bool(selection.get("validation_consumed")) or bool(selection.get("test_consumed")):
        raise HybridRouterSpecError("the selection block of the report declares a holdout read")


def selected_architecture(report: Mapping[str, Any]) -> str:
    name = (report.get("selection") or {}).get("selected")
    architectures = report.get("architectures") or {}
    if not name or name not in architectures:
        raise HybridRouterSpecError("the cross-validation report names no selected architecture")
    return str(name)


def cv_justification(
    report: Mapping[str, Any],
    breakdown_key: str,
    *,
    minimum_category_support: int,
    minimum_positive_gain_share: float,
) -> bool:
    """True when a categorical block is justified by the TRAIN out-of-fold folds.

    A block is admissible only when at least two of its categories clear the
    minimum support *and* the out-of-fold decisions those categories carry are
    answered with a strictly positive gain over the global action prior on the
    preponderant share of the eligible support.  The boolean (never the
    underlying counts) is persisted, so the frozen document holds no numeric
    train quantity.
    """
    architecture = report["architectures"][selected_architecture(report)]
    breakdown = architecture.get(breakdown_key) or {}
    eligible = {
        category: metrics
        for category, metrics in breakdown.items()
        if int(metrics.get("n") or 0) >= minimum_category_support
    }
    eligible_support = sum(int(metrics.get("n") or 0) for metrics in eligible.values())
    if len(eligible) < 2 or eligible_support <= 0:
        return False
    positive_support = sum(
        int(metrics.get("n") or 0)
        for metrics in eligible.values()
        if float(metrics.get("gain_bits_per_decision") or 0.0) > 0.0
    )
    return (positive_support / eligible_support) >= minimum_positive_gain_share


# --------------------------------------------------------------------------
# preregistered constants
# --------------------------------------------------------------------------

MINIMUM_CATEGORY_SUPPORT = 20
MINIMUM_POSITIVE_GAIN_SHARE = 0.5


def preregistered_constants() -> list[dict[str, Any]]:
    entries = [
        {
            "name": "NON_INFERIORITY_CONFIDENCE_LEVEL",
            "value": 0.95,
            "provenance": "preregistered router convention, aligned with the frozen #421 protocol",
        },
        {
            "name": "NON_INFERIORITY_UPPER_QUANTILE",
            "value": 0.95,
            "provenance": "one-sided upper percentile of the paired bootstrap (1 - alpha)",
        },
        {
            "name": "NON_INFERIORITY_ALPHA",
            "value": 0.05,
            "provenance": "preregistered one-sided tail of the paired non-inferiority bootstrap",
        },
        {
            "name": "BOOTSTRAP_SAMPLES",
            "value": 2000,
            "provenance": "preregistered paired percentile-bootstrap resample count",
        },
        {
            "name": "BOOTSTRAP_SEED",
            "value": 423,
            "provenance": "deterministic bootstrap seed of the issue-423 preregistration",
        },
        {
            "name": "MARGIN_MAX_BITS",
            "value": 0.0,
            "provenance": "preregistered maximum tolerated global non-inferiority margin",
        },
        {
            "name": "MARGIN_ANALYTIC_TOLERANCE_BITS",
            "value": 0.001,
            "provenance": "preregistered agreement tolerance between bootstrap and analytic margin",
        },
        {
            "name": "GAIN_FLOOR_BITS",
            "value": 0.0,
            "provenance": "preregistered minimum sparse gain over the global action prior",
        },
        {
            "name": "ECE_ABSOLUTE_CEILING",
            "value": 0.02,
            "provenance": "preregistered absolute expected-calibration-error ceiling",
        },
        {
            "name": "ECE_DELTA_CEILING",
            "value": 0.02,
            "provenance": "preregistered maximum sparse ECE delta against the active reference",
        },
        {
            "name": "FREQUENT_EXACT_MAX_DEGRADATION_BITS",
            "value": 0.0,
            "provenance": "preregistered non-degradation bound on the frequent-exact route",
        },
        {
            "name": "MINIMUM_SPARSE_OBSERVATIONS",
            "value": 20,
            "provenance": "repository minimum-support convention reused for the sparse floor",
        },
        {
            "name": "MINIMUM_CATEGORY_SUPPORT",
            "value": MINIMUM_CATEGORY_SUPPORT,
            "provenance": "minimum out-of-fold support before a categorical block may be consumed",
        },
        {
            "name": "MINIMUM_POSITIVE_GAIN_SHARE",
            "value": MINIMUM_POSITIVE_GAIN_SHARE,
            "provenance": "minimum eligible support share answered with positive gain",
        },
        {
            "name": "FREQUENT_EXACT_MIN_SUPPORT",
            "value": cv.FREQUENT_EXACT_MIN_SUPPORT,
            "provenance": "stratum threshold reused from the #421 TRAIN cross-validation",
        },
        {
            "name": "RARE_EXACT_MIN_SUPPORT",
            "value": cv.RARE_EXACT_MIN_SUPPORT,
            "provenance": "stratum threshold reused from the #421 TRAIN cross-validation",
        },
        {
            "name": "Z_ONE_SIDED_95",
            "value": 1.6448536269514722,
            "provenance": "standard normal one-sided 95% quantile used by the analytic margin",
        },
    ]
    #: Every constant is preregistered by construction: none of them is read off
    #: a VALIDATION or TEST evaluation.
    return [{**entry, "terminal_evaluation_derived": False} for entry in entries]


# --------------------------------------------------------------------------
# reason-code catalog (definitions only; the codes come from #421)
# --------------------------------------------------------------------------

REASON_DEFINITIONS: dict[str, str] = {
    "UNSEEN_CATEGORY": (
        "at least one single-feature node label of the context was never observed in the "
        "calibrated TRAIN domain"
    ),
    "EXTRAPOLATION_STACK": "the queried effective stack leaves the calibrated TRAIN stack domain",
    "EXTRAPOLATION_SIZING": "the queried raise target leaves the calibrated TRAIN sizing domain",
    "EXTRAPOLATION_PRICE": (
        "the queried to-call / pot price leaves the calibrated TRAIN price domain"
    ),
    "MISSING_DOMAIN_AXIS": (
        "a numeric domain axis required by the gate is absent from the request"
    ),
    "SPLINE_BOUNDARY_EXTRAPOLATION": (
        "the queried point sits on the frozen spline boundary, where the learned function is "
        "extrapolating"
    ),
    "DOMAIN_DISTANCE": "the robust domain distance exceeds its calibrated tail",
    "LOW_FEATURE_SUPPORT": "a single-feature label is below the calibrated minimum support share",
    "LOW_EXACT_CONTEXT_SUPPORT": (
        "the exact context signature is below the calibrated minimum exact-context share"
    ),
    "HIGH_PREDICTIVE_ENTROPY": (
        "the predictive distribution entropy exceeds its calibrated ceiling"
    ),
    "LOW_MODEL_NODE_SUPPORT": "the fitted node cell carries less than the calibrated support floor",
    "PREDICTIVE_UNCERTAINTY_UNAVAILABLE": (
        "no fitted model was available, so predictive uncertainty could not be computed"
    ),
}


def reason_codes_block() -> dict[str, Any]:
    catalog = []
    for code in grm.OOD_REASON_ORDER:
        hard = code in grm.OOD_HARD_REASONS
        catalog.append(
            {
                "code": code,
                "class": "hard" if hard else "soft",
                "abstains": hard,
                "definition": REASON_DEFINITIONS[code],
            }
        )
    return {
        "reused_from": "issue-421",
        "source_module_symbol": "tools/preflop/generalized_response_model.py::OOD_REASON_ORDER",
        "order": list(grm.OOD_REASON_ORDER),
        "hard": list(grm.OOD_HARD_REASONS),
        "soft": list(grm.OOD_SOFT_REASONS),
        "abstaining": list(grm.OOD_HARD_REASONS),
        "catalog": catalog,
    }


# --------------------------------------------------------------------------
# stable pre-action signals
# --------------------------------------------------------------------------

ROUTE_IDS = ("ACTIVE_STRONG_SUPPORT", "GENERALIZED_SPARSE_IN_DOMAIN", "OOD_ABSTAIN")

SIGNAL_SPECS: tuple[dict[str, Any], ...] = (
    {
        "id": "support_exact",
        "kind": "support",
        "definition": (
            "fit-fold occurrences of the decision's exact context signature at the model's own "
            "discrete resolution"
        ),
        "source_module_symbol": "evaluate_generalized_response_cv.exact_context_key",
        "read_from": "fit-fold exact_context_support",
        "used_by_route_sources": list(ROUTE_IDS),
        "used_by_formulas": ["STRATUM_ASSIGNMENT", "ROUTE_SELECTION_PROCEDURE"],
        "decisive_for_ood": False,
    },
    {
        "id": "support_feature_level",
        "kind": "support",
        "definition": (
            "weakest per-block share of the decision's single-feature node labels observed in the "
            "fit fold"
        ),
        "source_module_symbol": "evaluate_generalized_response_cv.FEATURE_BLOCKS",
        "read_from": "local_support.min_feature_share",
        "used_by_route_sources": ["GENERALIZED_SPARSE_IN_DOMAIN", "OOD_ABSTAIN"],
        "used_by_formulas": ["STRATUM_ASSIGNMENT", "ROUTE_SELECTION_PROCEDURE"],
        "decisive_for_ood": True,
    },
    {
        "id": "distance_to_domain",
        "kind": "domain",
        "definition": (
            "robust distance of the queried context to the calibrated numeric domain, computed on "
            "the frozen domain axes"
        ),
        "source_module_symbol": "generalized_response_model._ood_axis_distance",
        "read_from": "domain_distance",
        "used_by_route_sources": ["GENERALIZED_SPARSE_IN_DOMAIN", "OOD_ABSTAIN"],
        "used_by_formulas": ["OOD_ABSTENTION_CRITERION"],
        "decisive_for_ood": False,
    },
    {
        "id": "predictive_uncertainty",
        "kind": "uncertainty",
        "definition": (
            "normalized predictive entropy and fitted node support of the generalized channel, "
            "compared against the frozen calibration tails"
        ),
        "source_module_symbol": "generalized_response_model.ood_gate_decision",
        "read_from": "signals.predictive_uncertainty",
        "used_by_route_sources": ["GENERALIZED_SPARSE_IN_DOMAIN", "OOD_ABSTAIN"],
        "used_by_formulas": ["OOD_ABSTENTION_CRITERION"],
        "decisive_for_ood": False,
    },
    {
        "id": "extrapolation_sizing",
        "kind": "extrapolation",
        "definition": "the queried raise target leaves the calibrated TRAIN sizing domain",
        "source_module_symbol": "generalized_response_model.OOD_AXIS_EXTRAPOLATION_REASON",
        "read_from": "signals.axes.sizing_ratio",
        "used_by_route_sources": ["OOD_ABSTAIN"],
        "used_by_formulas": ["OOD_ABSTENTION_CRITERION"],
        "decisive_for_ood": True,
    },
    {
        "id": "extrapolation_stack",
        "kind": "extrapolation",
        "definition": "the queried effective stack leaves the calibrated TRAIN stack domain",
        "source_module_symbol": "generalized_response_model.OOD_AXIS_EXTRAPOLATION_REASON",
        "read_from": "signals.axes.effective_stack_bb",
        "used_by_route_sources": ["OOD_ABSTAIN"],
        "used_by_formulas": ["OOD_ABSTENTION_CRITERION"],
        "decisive_for_ood": True,
    },
    {
        "id": "extrapolation_price",
        "kind": "extrapolation",
        "definition": "the queried to-call / pot price leaves the calibrated TRAIN price domain",
        "source_module_symbol": "generalized_response_model.OOD_AXIS_EXTRAPOLATION_REASON",
        "read_from": "signals.axes.to_call_bb|pot_before_bb",
        "used_by_route_sources": ["OOD_ABSTAIN"],
        "used_by_formulas": ["OOD_ABSTENTION_CRITERION"],
        "decisive_for_ood": True,
    },
    {
        "id": "family",
        "kind": "categorical",
        "definition": (
            "public family block; consumed by a route only where the TRAIN out-of-fold breakdown "
            "justifies it"
        ),
        "source_module_symbol": "generalized_response_model.CATEGORICAL_BLOCKS",
        "read_from": "public context family",
        "used_by_route_sources": ["ACTIVE_STRONG_SUPPORT", "GENERALIZED_SPARSE_IN_DOMAIN"],
        "used_by_formulas": [],
        "decisive_for_ood": False,
    },
    {
        "id": "actor_position",
        "kind": "categorical",
        "definition": (
            "public actor position block; consumed by a route only where the TRAIN out-of-fold "
            "breakdown justifies it"
        ),
        "source_module_symbol": "generalized_response_model.CATEGORICAL_BLOCKS",
        "read_from": "public context actor_position",
        "used_by_route_sources": ["ACTIVE_STRONG_SUPPORT", "GENERALIZED_SPARSE_IN_DOMAIN"],
        "used_by_formulas": [],
        "decisive_for_ood": False,
    },
    {
        "id": "aggressor_position",
        "kind": "categorical",
        "definition": (
            "public aggressor position block; consumed by a route only where the TRAIN out-of-fold "
            "breakdown justifies it"
        ),
        "source_module_symbol": "generalized_response_model.CATEGORICAL_BLOCKS",
        "read_from": "public context aggressor_position",
        "used_by_route_sources": ["ACTIVE_STRONG_SUPPORT", "GENERALIZED_SPARSE_IN_DOMAIN"],
        "used_by_formulas": [],
        "decisive_for_ood": False,
    },
)

#: Categorical signals whose use is gated on a TRAIN out-of-fold justification.
CATEGORICAL_JUSTIFICATION_KEYS = {
    "family": "by_family",
    "actor_position": "by_actor_position",
    "aggressor_position": "by_aggressor_position",
}


def signals_block(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    signals = []
    for spec in SIGNAL_SPECS:
        requires = spec["id"] in CATEGORICAL_JUSTIFICATION_KEYS
        if requires:
            justified = cv_justification(
                report,
                CATEGORICAL_JUSTIFICATION_KEYS[spec["id"]],
                minimum_category_support=MINIMUM_CATEGORY_SUPPORT,
                minimum_positive_gain_share=MINIMUM_POSITIVE_GAIN_SHARE,
            )
            basis = (
                "TRAIN out-of-fold breakdown: at least two eligible categories and a preponderant "
                "share of eligible support answered with positive gain over the global action prior"
            )
        else:
            justified = True
            basis = "mechanically defined before the action; no train tuning required"
        signals.append(
            {
                "id": spec["id"],
                "timing": "BEFORE_ACTION",
                "deterministic": True,
                "computable_before_action": True,
                "kind": spec["kind"],
                "definition": spec["definition"],
                "source_module_symbol": spec["source_module_symbol"],
                "read_from": spec["read_from"],
                "used_by_route_sources": list(spec["used_by_route_sources"]),
                "used_by_formulas": list(spec["used_by_formulas"]),
                "decisive_for_ood": bool(spec["decisive_for_ood"]),
                "admissibility": {
                    "requires_cv_justification": requires,
                    "cv_justified": justified,
                    "basis": basis,
                    "minimum_category_support": MINIMUM_CATEGORY_SUPPORT,
                    "minimum_positive_gain_share": MINIMUM_POSITIVE_GAIN_SHARE,
                },
            }
        )
    return signals


# --------------------------------------------------------------------------
# route sources and decision table
# --------------------------------------------------------------------------


def route_sources_block() -> list[dict[str, Any]]:
    return [
        {
            "id": "ACTIVE_STRONG_SUPPORT",
            "decision_priority": "P2",
            "definition": (
                "answer from the active reference population model, admissible only where the exact "
                "context is strongly supported"
            ),
            "model_id": "active_model_a_preflop_population",
            "probabilities_source": "frozen active reference probabilities",
            "abstains": False,
            "support_state": "STRONG_EXACT_SUPPORT",
            "preconditions": [
                {
                    "signal": "support_exact",
                    "operator": ">=",
                    "reference": "FREQUENT_EXACT_MIN_SUPPORT",
                },
                {
                    "signal": "hard_reasons",
                    "operator": "is_empty",
                    "reference": "OOD_HARD_REASONS",
                },
            ],
            "routed_strata": ["frequent_exact"],
        },
        {
            "id": "GENERALIZED_SPARSE_IN_DOMAIN",
            "decision_priority": "P3",
            "definition": (
                "answer from the learned generalized response channel where the exact context is "
                "sparse or absent but every single-feature label stays inside the calibrated domain"
            ),
            "model_id": "generalized_adverse_response_candidate_v1",
            "probabilities_source": "generalized channel legal-action distribution",
            "abstains": False,
            "support_state": "SPARSE_IN_DOMAIN",
            "preconditions": [
                {
                    "signal": "support_feature_level",
                    "operator": ">=",
                    "reference": "feature_in_domain",
                },
                {
                    "signal": "hard_reasons",
                    "operator": "is_empty",
                    "reference": "OOD_HARD_REASONS",
                },
            ],
            "routed_strata": ["rare_exact", "exact_absent_in_domain"],
        },
        {
            "id": "OOD_ABSTAIN",
            "decision_priority": "P1",
            "definition": (
                "fail closed: no route may answer, no probabilities and no sizing are emitted, and "
                "the decision is excluded from every predictive gate"
            ),
            "model_id": "none",
            "probabilities_source": "no probabilities: the decision abstains",
            "abstains": True,
            "support_state": "OOD_ABSTAIN",
            "preconditions": [
                {
                    "signal": "hard_reasons",
                    "operator": "is_not_empty",
                    "reference": "OOD_HARD_REASONS",
                }
            ],
            "routed_strata": ["exact_absent_out_of_domain"],
        },
    ]


def route_decision_table_block() -> list[dict[str, Any]]:
    return [
        {
            "row": "R1",
            "when": "hard_reasons(context) is not empty",
            "route_source": "OOD_ABSTAIN",
            "fallback": False,
        },
        {
            "row": "R2",
            "when": "hard_reasons(context) is empty and support_exact >= FREQUENT_EXACT_MIN_SUPPORT",
            "route_source": "ACTIVE_STRONG_SUPPORT",
            "fallback": False,
        },
        {
            "row": "R3",
            "when": "hard_reasons(context) is empty and feature_in_domain(context)",
            "route_source": "GENERALIZED_SPARSE_IN_DOMAIN",
            "fallback": False,
        },
        {
            "row": "R4",
            "when": "no earlier row matched",
            "route_source": "OOD_ABSTAIN",
            "fallback": True,
        },
    ]


# --------------------------------------------------------------------------
# runtime contract
# --------------------------------------------------------------------------


def runtime_contract_block() -> dict[str, Any]:
    fields = [
        {
            "name": "route_source",
            "type": "enum[ACTIVE_STRONG_SUPPORT|GENERALIZED_SPARSE_IN_DOMAIN|OOD_ABSTAIN]",
            "required": True,
            "required_when": None,
            "definition": "the route source that produced this decision, always present",
        },
        {
            "name": "model_id",
            "type": "string",
            "required": True,
            "required_when": None,
            "definition": "stable identity of the model that produced the probabilities",
        },
        {
            "name": "model_hash",
            "type": "sha256",
            "required": True,
            "required_when": None,
            "definition": "byte digest of the model artifact the probabilities were read from",
        },
        {
            "name": "support_state",
            "type": "enum[STRONG_EXACT_SUPPORT|SPARSE_IN_DOMAIN|OOD_ABSTAIN]",
            "required": True,
            "required_when": None,
            "definition": "support classification of the request, derived from route_source",
        },
        {
            "name": "uncertainty",
            "type": "enum[NONE|HIGH]",
            "required": True,
            "required_when": None,
            "definition": "HIGH when the gate raised any soft reason, NONE otherwise",
        },
        {
            "name": "ood_status",
            "type": "enum[MODEL_SUPPORTED|MODEL_SUPPORTED_HIGH_UNCERTAINTY|MODEL_OOD_ABSTAIN]",
            "required": True,
            "required_when": None,
            "definition": "status returned by the frozen #421 OOD / uncertainty gate",
        },
        {
            "name": "probabilities",
            "type": "object[FOLD|CALL|RAISE|JAM]->number",
            "required": True,
            "required_when": "route_source != OOD_ABSTAIN",
            "definition": (
                "legal-action distribution summing to one with zero mass on illegal actions; "
                "absent on an abstention"
            ),
        },
        {
            "name": "sizing_provenance",
            "type": "object",
            "required": False,
            "required_when": "selected_action in {RAISE, JAM}",
            "definition": (
                "the sizing channel, its legality window verdict and the queried target of a raise "
                "or jam answer"
            ),
        },
        {
            "name": "analysis_admissible",
            "type": "boolean",
            "required": True,
            "required_when": None,
            "definition": (
                "true only when the decision is answered (no abstention), the probabilities are "
                "legal and the sizing provenance is present on RAISE / JAM"
            ),
        },
    ]
    return {
        "schema": RUNTIME_CONTRACT_SCHEMA,
        "required_fields": [
            "route_source",
            "model_id",
            "model_hash",
            "support_state",
            "uncertainty",
            "ood_status",
            "analysis_admissible",
        ],
        "fields": fields,
        "invariants": [
            "route_source is always one of the three declared route sources",
            "an OOD_ABSTAIN answer carries no probabilities, no selected action and no sizing",
            "analysis_admissible is false on every abstention",
            "a RAISE or JAM answer carries the sizing provenance of the channel that produced it",
            "the emitted probabilities sum to one with zero mass on illegal actions",
        ],
        "abstention_contract": {
            "route_source": "OOD_ABSTAIN",
            "probabilities_present": False,
            "selected_action_present": False,
            "reason_codes_present": True,
            "analysis_admissible": False,
        },
        "sizing_contract": {
            "required_actions": ["RAISE", "JAM"],
            "field": "sizing_provenance",
            "no_nearest_price_substitution": True,
            "fail_closed_on_illegal_target": True,
        },
        "analysis_admissibility_rule": (
            "analysis_admissible = (route_source != OOD_ABSTAIN) and probabilities legal and "
            "(sizing_provenance present when the selected action is RAISE or JAM)"
        ),
    }


def strata_block() -> dict[str, Any]:
    roles = {
        "frequent_exact": ("strong exact support", "ACTIVE_STRONG_SUPPORT", False),
        "rare_exact": ("sparse but observed exact support", "GENERALIZED_SPARSE_IN_DOMAIN", True),
        "exact_absent_in_domain": (
            "exact cell never observed while every single-feature label is in domain",
            "GENERALIZED_SPARSE_IN_DOMAIN",
            True,
        ),
        "exact_absent_out_of_domain": (
            "exact cell never observed with at least one unseen feature value",
            "OOD_ABSTAIN",
            False,
        ),
    }
    strata = [
        {
            "id": name,
            "role": roles[name][0],
            "routed_to": roles[name][1],
            "covered_by_sparse_floor": roles[name][2],
        }
        for name in cv.STRATA
    ]
    return {
        "reused_from": "issue-421",
        "source_module_symbol": (
            "tools/training/evaluate_generalized_response_cv.py::STRATA/STRATA_DEFINITION"
        ),
        "definition": cv.STRATA_DEFINITION,
        "support_thresholds": {
            "frequent_exact_min_support": cv.FREQUENT_EXACT_MIN_SUPPORT,
            "rare_exact_min_support": cv.RARE_EXACT_MIN_SUPPORT,
        },
        "strata": strata,
        "sparse_covered_strata": ["rare_exact", "exact_absent_in_domain"],
        "ood_strata": ["exact_absent_out_of_domain"],
    }


def ood_gate_block() -> dict[str, Any]:
    contract = json.loads(OOD_GATE_SCHEMA_PATH.read_text(encoding="utf-8"))
    thresholds = contract["$defs"]["thresholds"]["required"]
    return {
        "reused_from": "issue-421",
        "schema": grm.OOD_GATE_SCHEMA,
        "contract_path": OOD_GATE_SCHEMA_LOGICAL_PATH,
        "contract_sha256": sha256_file(OOD_GATE_SCHEMA_PATH),
        "statuses": list(grm.OOD_STATUSES),
        "status_definitions": dict(grm.OOD_STATUS_DEFINITIONS),
        "hard_reason_codes": list(grm.OOD_HARD_REASONS),
        "soft_reason_codes": list(grm.OOD_SOFT_REASONS),
        "threshold_keys": list(thresholds),
        "abstention_criterion_formula": "OOD_ABSTENTION_CRITERION",
        "high_uncertainty_rule": (
            "no hard reason and at least one soft reason raises the status to "
            "MODEL_SUPPORTED_HIGH_UNCERTAINTY without abstaining"
        ),
        "exact_context_absent_in_domain_decisive": False,
    }


# --------------------------------------------------------------------------
# formula library
# --------------------------------------------------------------------------


def _input(symbol: str, source: str, pointer: str | None = None) -> dict[str, Any]:
    return {"symbol": symbol, "source": source, "pointer": pointer}


def _train_pointer(block: str, stratum: str) -> str:
    return f"/architectures/{{selected}}/strata/{block}/{stratum}"


def r_and(name: str) -> dict[str, Any]:
    return {"op": "const_ref", "name": name}


def sym(name: str) -> dict[str, Any]:
    return {"op": "symbol", "name": name}


def build_formulas() -> list[dict[str, Any]]:
    """The exact derivation procedure, with an executable mirror in ``_machine``.

    The ``_machine`` key is stripped before the document is persisted and
    hashed: the frozen spec keeps the exact textual expression, its symbols, its
    inputs and its acceptance criterion.  The mirror is what
    :func:`evaluate_train_only` runs, so a formula cannot be declared without
    also being computable.
    """
    sparse_weights = [sym("n.rare_exact"), sym("n.exact_absent_in_domain")]
    sparse_gain_values = [sym("gain.rare_exact"), sym("gain.exact_absent_in_domain")]
    sparse_ece_values = [sym("ece.rare_exact"), sym("ece.exact_absent_in_domain")]
    return [
        {
            "id": "GLOBAL_NON_INFERIORITY_MARGIN",
            "derives": "margin_global",
            "direction": "lower_is_better",
            "evaluation_surface": "FROZEN_ADMISSION_SUPPORT",
            "strata_scope": ["frequent_exact", "rare_exact", "exact_absent_in_domain"],
            "expression": (
                "margin_global = quantile(paired_bootstrap(hand_id, B=BOOTSTRAP_SAMPLES, "
                "seed=BOOTSTRAP_SEED) of delta = loss_hybrid - loss_active, "
                "NON_INFERIORITY_UPPER_QUANTILE)"
            ),
            "symbols": ["delta.pooled"],
            "inputs": [_input("delta.pooled", "frozen_admission_support")],
            "constant_refs": [
                "BOOTSTRAP_SAMPLES",
                "BOOTSTRAP_SEED",
                "NON_INFERIORITY_UPPER_QUANTILE",
                "MARGIN_MAX_BITS",
            ],
            "criterion": "margin_global <= MARGIN_MAX_BITS",
            "notes": (
                "the margin is the one-sided upper percentile of the paired bootstrap of the "
                "hybrid-minus-active loss on the frozen admission support"
            ),
            "_machine": {
                "value": {
                    "op": "quantile",
                    "args": [sym("delta.pooled"), r_and("NON_INFERIORITY_UPPER_QUANTILE")],
                },
                "criterion": {
                    "op": "le",
                    "args": [sym("margin_global"), r_and("MARGIN_MAX_BITS")],
                },
            },
        },
        {
            "id": "GLOBAL_NON_INFERIORITY_ANALYTIC_CROSS_CHECK",
            "derives": "margin_global_analytic",
            "direction": "lower_is_better",
            "evaluation_surface": "FROZEN_ADMISSION_SUPPORT",
            "strata_scope": ["frequent_exact", "rare_exact", "exact_absent_in_domain"],
            "expression": (
                "margin_global_analytic = mean(delta.pooled) + Z_ONE_SIDED_95 * se(delta.pooled)"
            ),
            "symbols": ["mean.pooled", "se.pooled"],
            "inputs": [
                _input("mean.pooled", "frozen_admission_support"),
                _input("se.pooled", "frozen_admission_support"),
            ],
            "constant_refs": [
                "Z_ONE_SIDED_95",
                "MARGIN_ANALYTIC_TOLERANCE_BITS",
                "MARGIN_MAX_BITS",
            ],
            "criterion": (
                "abs(margin_global_analytic - margin_global) <= MARGIN_ANALYTIC_TOLERANCE_BITS "
                "and margin_global_analytic <= MARGIN_MAX_BITS"
            ),
            "notes": (
                "closed-form cross-check of the bootstrap margin; the two must agree within the "
                "preregistered tolerance"
            ),
            "_machine": {
                "value": {
                    "op": "add",
                    "args": [
                        sym("mean.pooled"),
                        {
                            "op": "mul",
                            "args": [r_and("Z_ONE_SIDED_95"), sym("se.pooled")],
                        },
                    ],
                },
            },
        },
        {
            "id": "SPARSE_GAIN_FLOOR",
            "derives": "gain_sparse",
            "direction": "higher_is_better",
            "evaluation_surface": "TRAIN_OUT_OF_FOLD",
            "strata_scope": ["rare_exact", "exact_absent_in_domain"],
            "expression": (
                "gain_sparse = (n.rare_exact * gain.rare_exact + n.exact_absent_in_domain * "
                "gain.exact_absent_in_domain) / (n.rare_exact + n.exact_absent_in_domain)"
            ),
            "symbols": [
                "n.rare_exact",
                "n.exact_absent_in_domain",
                "gain.rare_exact",
                "gain.exact_absent_in_domain",
            ],
            "inputs": [
                _input("n.rare_exact", "train_out_of_fold_cv_report", _train_pointer("counts", "rare_exact")),
                _input(
                    "n.exact_absent_in_domain",
                    "train_out_of_fold_cv_report",
                    _train_pointer("counts", "exact_absent_in_domain"),
                ),
                _input(
                    "gain.rare_exact",
                    "train_out_of_fold_cv_report",
                    _train_pointer("metrics", "rare_exact"),
                ),
                _input(
                    "gain.exact_absent_in_domain",
                    "train_out_of_fold_cv_report",
                    _train_pointer("metrics", "exact_absent_in_domain"),
                ),
            ],
            "constant_refs": [
                "GAIN_FLOOR_BITS",
                "MINIMUM_SPARSE_OBSERVATIONS",
                "FREQUENT_EXACT_MIN_SUPPORT",
            ],
            "criterion": (
                "gain_sparse >= GAIN_FLOOR_BITS and min(gain.rare_exact, "
                "gain.exact_absent_in_domain) >= GAIN_FLOOR_BITS and "
                "(n.rare_exact + n.exact_absent_in_domain) >= MINIMUM_SPARSE_OBSERVATIONS"
            ),
            "notes": (
                "the sparse floor pools exactly rare_exact and exact_absent_in_domain, the two "
                "strata the generalized channel is allowed to cover; the {selected} placeholder "
                "of the inputs resolves to the architecture selected by the frozen TRAIN cross-"
                "validation"
            ),
            "_machine": {
                "value": {
                    "op": "weighted_mean",
                    "weights": sparse_weights,
                    "values": sparse_gain_values,
                },
                "criterion": {
                    "op": "and",
                    "args": [
                        {"op": "ge", "args": [sym("gain_sparse"), r_and("GAIN_FLOOR_BITS")]},
                        {
                            "op": "ge",
                            "args": [
                                {"op": "min", "args": sparse_gain_values},
                                r_and("GAIN_FLOOR_BITS"),
                            ],
                        },
                        {
                            "op": "ge",
                            "args": [
                                {"op": "sum", "args": sparse_weights},
                                r_and("MINIMUM_SPARSE_OBSERVATIONS"),
                            ],
                        },
                    ],
                },
            },
        },
        {
            "id": "SPARSE_GAIN_FLOOR_PAIRED_LOWER_BOUND",
            "derives": "gain_sparse_lower_bound",
            "direction": "higher_is_better",
            "evaluation_surface": "FROZEN_ADMISSION_SUPPORT",
            "strata_scope": ["rare_exact", "exact_absent_in_domain"],
            "expression": (
                "gain_sparse_lower_bound = quantile(paired_bootstrap(hand_id, "
                "B=BOOTSTRAP_SAMPLES, seed=BOOTSTRAP_SEED) of gain_sparse, NON_INFERIORITY_ALPHA)"
            ),
            "symbols": ["delta.sparse"],
            "inputs": [_input("delta.sparse", "frozen_admission_support")],
            "constant_refs": [
                "BOOTSTRAP_SAMPLES",
                "BOOTSTRAP_SEED",
                "NON_INFERIORITY_ALPHA",
                "GAIN_FLOOR_BITS",
            ],
            "criterion": "gain_sparse_lower_bound >= GAIN_FLOOR_BITS",
            "notes": (
                "conservative admission form of the sparse floor: the lower paired-bootstrap "
                "percentile of the sparse gain must stay above the floor"
            ),
            "_machine": {
                "value": {
                    "op": "quantile",
                    "args": [sym("delta.sparse"), r_and("NON_INFERIORITY_ALPHA")],
                },
            },
        },
        {
            "id": "SPARSE_ECE_MEASUREMENT",
            "derives": "ece_sparse",
            "direction": "lower_is_better",
            "evaluation_surface": "TRAIN_OUT_OF_FOLD",
            "strata_scope": ["rare_exact", "exact_absent_in_domain"],
            "expression": (
                "ece_sparse = (n.rare_exact * ece.rare_exact + n.exact_absent_in_domain * "
                "ece.exact_absent_in_domain) / (n.rare_exact + n.exact_absent_in_domain)"
            ),
            "symbols": [
                "n.rare_exact",
                "n.exact_absent_in_domain",
                "ece.rare_exact",
                "ece.exact_absent_in_domain",
            ],
            "inputs": [
                _input("n.rare_exact", "train_out_of_fold_cv_report", _train_pointer("counts", "rare_exact")),
                _input(
                    "n.exact_absent_in_domain",
                    "train_out_of_fold_cv_report",
                    _train_pointer("counts", "exact_absent_in_domain"),
                ),
                _input(
                    "ece.rare_exact",
                    "train_out_of_fold_cv_report",
                    _train_pointer("metrics", "rare_exact"),
                ),
                _input(
                    "ece.exact_absent_in_domain",
                    "train_out_of_fold_cv_report",
                    _train_pointer("metrics", "exact_absent_in_domain"),
                ),
            ],
            "constant_refs": ["ECE_ABSOLUTE_CEILING"],
            "criterion": "ece_sparse <= ECE_ABSOLUTE_CEILING",
            "notes": (
                "support-weighted sparse calibration error on the same two strata as the sparse "
                "gain floor; the {selected} placeholder of the inputs resolves to the architecture "
                "selected by the frozen TRAIN cross-validation"
            ),
            "_machine": {
                "value": {
                    "op": "weighted_mean",
                    "weights": sparse_weights,
                    "values": sparse_ece_values,
                },
            },
        },
        {
            "id": "SPARSE_ECE_CEILING",
            "derives": "ece_ceiling_sparse",
            "direction": "lower_is_better",
            "evaluation_surface": "FROZEN_ADMISSION_SUPPORT",
            "strata_scope": ["rare_exact", "exact_absent_in_domain"],
            "expression": (
                "ece_ceiling_sparse = min(ECE_ABSOLUTE_CEILING, "
                "ece_active_sparse + ECE_DELTA_CEILING)"
            ),
            "symbols": ["ece.active_sparse"],
            "inputs": [_input("ece.active_sparse", "frozen_admission_support")],
            "constant_refs": ["ECE_ABSOLUTE_CEILING", "ECE_DELTA_CEILING"],
            "criterion": "ece_sparse <= ece_ceiling_sparse",
            "notes": (
                "the sparse ceiling is the tighter of the absolute ceiling and the active "
                "reference ECE plus the preregistered delta"
            ),
            "_machine": {
                "value": {
                    "op": "min",
                    "args": [
                        r_and("ECE_ABSOLUTE_CEILING"),
                        {
                            "op": "add",
                            "args": [sym("ece.active_sparse"), r_and("ECE_DELTA_CEILING")],
                        },
                    ],
                },
            },
        },
        {
            "id": "FREQUENT_EXACT_NON_DEGRADATION_BOUND",
            "derives": "bound_frequent_exact",
            "direction": "lower_is_better",
            "evaluation_surface": "FROZEN_ADMISSION_SUPPORT",
            "strata_scope": ["frequent_exact"],
            "expression": (
                "delta_frequent_exact = loss.hybrid.frequent_exact - "
                "loss.active.frequent_exact; bound_frequent_exact = "
                "FREQUENT_EXACT_MAX_DEGRADATION_BITS"
            ),
            "symbols": ["loss.hybrid.frequent_exact", "loss.active.frequent_exact"],
            "inputs": [
                _input("loss.hybrid.frequent_exact", "frozen_admission_support"),
                _input("loss.active.frequent_exact", "frozen_admission_support"),
            ],
            "constant_refs": ["FREQUENT_EXACT_MAX_DEGRADATION_BITS"],
            "criterion": (
                "delta_frequent_exact <= bound_frequent_exact and "
                "paired_ci_upper(delta_frequent_exact) <= bound_frequent_exact"
            ),
            "notes": (
                "the frequent-exact route must never degrade the active reference beyond the "
                "preregistered bound, in point estimate and in paired upper bound"
            ),
            "_machine": {
                "value": {
                    "op": "sub",
                    "args": [
                        sym("loss.hybrid.frequent_exact"),
                        sym("loss.active.frequent_exact"),
                    ],
                },
                "criterion": {
                    "op": "le",
                    "args": [
                        sym("delta_frequent_exact"),
                        r_and("FREQUENT_EXACT_MAX_DEGRADATION_BITS"),
                    ],
                },
            },
        },
        {
            "id": "OOD_ABSTENTION_CRITERION",
            "derives": "abstain",
            "direction": "predicate",
            "evaluation_surface": "RUNTIME_GATE",
            "strata_scope": ["exact_absent_out_of_domain"],
            "expression": (
                "hard_reasons(c) = reasons(c) intersect OOD_HARD_REASONS; "
                "abstain(c) iff hard_reasons(c) is not empty; "
                "high_uncertainty(c) iff hard_reasons(c) is empty and soft_reasons(c) is not empty"
            ),
            "symbols": ["hard_reasons", "soft_reasons"],
            "inputs": [
                _input("hard_reasons", "runtime_gate"),
                _input("soft_reasons", "runtime_gate"),
            ],
            "constant_refs": ["FREQUENT_EXACT_MIN_SUPPORT"],
            "criterion": "route_source(c) == OOD_ABSTAIN iff abstain(c)",
            "notes": (
                "abstention is decided by the hard reason set only; an exact cell absent while "
                "every single-feature label is in domain is never decisive"
            ),
            "_machine": {
                "value": {
                    "op": "not",
                    "args": [{"op": "is_empty", "args": [sym("hard_reasons")]}],
                },
            },
        },
        {
            "id": "ROUTE_SELECTION_PROCEDURE",
            "derives": "route_source",
            "direction": "predicate",
            "evaluation_surface": "RUNTIME_GATE",
            "strata_scope": list(cv.STRATA),
            "expression": (
                "route_source(c) = OOD_ABSTAIN if hard_reasons(c) is not empty else "
                "ACTIVE_STRONG_SUPPORT if support_exact(c) >= FREQUENT_EXACT_MIN_SUPPORT else "
                "GENERALIZED_SPARSE_IN_DOMAIN if feature_in_domain(c) else OOD_ABSTAIN"
            ),
            "symbols": ["hard_reasons", "support_exact", "feature_in_domain"],
            "inputs": [
                _input("hard_reasons", "runtime_gate"),
                _input("support_exact", "runtime_gate"),
                _input("feature_in_domain", "runtime_gate"),
            ],
            "constant_refs": ["FREQUENT_EXACT_MIN_SUPPORT", "RARE_EXACT_MIN_SUPPORT"],
            "criterion": "route_source(c) equals the first matching row of the route decision table",
            "notes": (
                "the ordered decision table R1..R4 is the single source of the route; the last row "
                "is a fail-closed fallback onto OOD_ABSTAIN"
            ),
            "_machine": {"value": {"op": "not_evaluable", "args": []}},
        },
        {
            "id": "SUPPORT_STATE_ASSIGNMENT",
            "derives": "support_state",
            "direction": "predicate",
            "evaluation_surface": "RUNTIME_GATE",
            "strata_scope": list(cv.STRATA),
            "expression": (
                "support_state(c) = STRONG_EXACT_SUPPORT if route_source(c) == "
                "ACTIVE_STRONG_SUPPORT else SPARSE_IN_DOMAIN if route_source(c) == "
                "GENERALIZED_SPARSE_IN_DOMAIN else OOD_ABSTAIN"
            ),
            "symbols": ["route_source"],
            "inputs": [_input("route_source", "runtime_gate")],
            "constant_refs": ["FREQUENT_EXACT_MIN_SUPPORT"],
            "criterion": "support_state is the support state declared by the selected route source",
            "notes": (
                "support_state mirrors the selected route source so a consumer never re-derives it"
            ),
            "_machine": {"value": {"op": "not_evaluable", "args": []}},
        },
        {
            "id": "STRATUM_ASSIGNMENT",
            "derives": "stratum",
            "direction": "predicate",
            "evaluation_surface": "TRAIN_OUT_OF_FOLD",
            "strata_scope": list(cv.STRATA),
            "expression": (
                "stratum(c) = frequent_exact if support_exact(c) >= FREQUENT_EXACT_MIN_SUPPORT "
                "else rare_exact if support_exact(c) >= RARE_EXACT_MIN_SUPPORT else "
                "exact_absent_in_domain if feature_in_domain(c) else exact_absent_out_of_domain"
            ),
            "symbols": ["support_exact", "feature_in_domain"],
            "inputs": [
                _input("support_exact", "runtime_gate"),
                _input("feature_in_domain", "runtime_gate"),
            ],
            "constant_refs": ["FREQUENT_EXACT_MIN_SUPPORT", "RARE_EXACT_MIN_SUPPORT"],
            "criterion": "every held-out decision receives exactly one of the four frozen strata",
            "notes": (
                "the stratum of a decision is a pure function of the fit-fold exact support and of "
                "the single-feature in-domain verdict"
            ),
            "_machine": {"value": {"op": "not_evaluable", "args": []}},
        },
    ]


# --------------------------------------------------------------------------
# executable mirror (self-check only; never persisted as numbers)
# --------------------------------------------------------------------------

_MACHINE_OPERATORS = (
    "symbol",
    "const_ref",
    "add",
    "sub",
    "mul",
    "div",
    "min",
    "max",
    "mean",
    "weighted_mean",
    "sum",
    "quantile",
    "ge",
    "le",
    "gt",
    "lt",
    "and",
    "or",
    "not",
    "is_empty",
    "not_evaluable",
)


def _resolve_symbol(name: str, bindings: Mapping[str, Any]) -> Any:
    if name not in bindings or bindings[name] is None:
        return None
    return bindings[name]


def evaluate_machine(node: Mapping[str, Any], bindings: Mapping[str, Any]) -> Any:
    """Evaluate the executable mirror of a formula; ``None`` when not evaluable."""
    op = node.get("op")
    if op not in _MACHINE_OPERATORS:
        raise HybridRouterSpecError(f"unknown machine operator: {op!r}")
    if op == "not_evaluable":
        return None
    if op == "symbol":
        return _resolve_symbol(str(node["name"]), bindings)
    if op == "const_ref":
        return bindings.get("constants", {}).get(str(node["name"]))
    if op == "weighted_mean":
        weights = [evaluate_machine(item, bindings) for item in node["weights"]]
        values = [evaluate_machine(item, bindings) for item in node["values"]]
        if any(item is None for item in weights) or any(item is None for item in values):
            return None
        total = float(sum(weights))
        if total <= 0.0:
            return None
        return float(sum(float(w) * float(v) for w, v in zip(weights, values)) / total)
    if op == "quantile":
        return None  # a bootstrap percentile needs the frozen admission resamples
    args = [evaluate_machine(item, bindings) for item in node.get("args", ())]
    if op == "is_empty":
        target = args[0]
        return None if target is None else len(target) == 0
    if op == "not":
        return None if args[0] is None else (not args[0])
    if any(item is None for item in args):
        return None
    if op == "add":
        return float(sum(args))
    if op == "sub":
        return float(args[0]) - float(args[1])
    if op == "mul":
        return float(args[0]) * float(args[1])
    if op == "div":
        return float(args[0]) / float(args[1]) if float(args[1]) != 0.0 else None
    if op == "min":
        return float(min(args))
    if op == "max":
        return float(max(args))
    if op == "mean":
        return float(sum(args) / len(args)) if args else None
    if op == "sum":
        return float(sum(args))
    if op == "ge":
        return bool(args[0] >= args[1])
    if op == "le":
        return bool(args[0] <= args[1])
    if op == "gt":
        return bool(args[0] > args[1])
    if op == "lt":
        return bool(args[0] < args[1])
    if op == "and":
        return bool(all(args))
    if op == "or":
        return bool(any(args))
    raise HybridRouterSpecError(f"unhandled machine operator: {op!r}")


def train_only_bindings(report: Mapping[str, Any]) -> dict[str, Any]:
    """Bind the TRAIN out-of-fold symbols used by the evaluable formulas."""
    architecture = report["architectures"][selected_architecture(report)]
    counts = architecture["strata"]["counts"]
    metrics = architecture["strata"]["metrics"]

    def metric(stratum: str, field: str) -> float | None:
        block = metrics.get(stratum) or {}
        if field == "expected_calibration_error":
            return (block.get("expected_calibration_error") or {}).get("ece")
        return block.get(field)

    return {
        "n.rare_exact": counts.get("rare_exact"),
        "n.exact_absent_in_domain": counts.get("exact_absent_in_domain"),
        "gain.rare_exact": metric("rare_exact", "gain_bits_per_decision"),
        "gain.exact_absent_in_domain": metric("exact_absent_in_domain", "gain_bits_per_decision"),
        "ece.rare_exact": metric("rare_exact", "expected_calibration_error"),
        "ece.exact_absent_in_domain": metric("exact_absent_in_domain", "expected_calibration_error"),
        "constants": {entry["name"]: entry["value"] for entry in preregistered_constants()},
    }


def evaluate_train_only(
    report: Mapping[str, Any],
    formulas: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Evaluate every TRAIN-only formula on real out-of-fold evidence."""
    library = list(formulas) if formulas is not None else build_formulas()
    bindings = train_only_bindings(report)
    report_by_id: dict[str, Any] = {}
    for formula in library:
        machine = formula.get("_machine") or {}
        surface = formula.get("evaluation_surface")
        value_node = machine.get("value")
        if surface != "TRAIN_OUT_OF_FOLD" or not value_node:
            report_by_id[str(formula["id"])] = {"evaluable": False, "value": None}
            continue
        value = evaluate_machine(value_node, bindings)
        report_by_id[str(formula["id"])] = {"evaluable": value is not None, "value": value}
    return report_by_id


# --------------------------------------------------------------------------
# spec assembly
# --------------------------------------------------------------------------


def _strip_private(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: _strip_private(item)
            for key, item in value.items()
            if not str(key).startswith("_")
        }
    if isinstance(value, (list, tuple)):
        return [_strip_private(item) for item in value]
    return value


def build_spec(
    *,
    consumed_splits: Sequence[str] = CONSUMED_SPLITS,
    formulas: Sequence[Mapping[str, Any]] | None = None,
    report: Mapping[str, Any] | None = None,
    source_scan: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble the frozen document.  Fails closed on any refused split."""
    resolved_splits = assert_allowed_splits(consumed_splits)
    evidence_report = report if report is not None else load_train_cv_report()
    assert_train_only_report(evidence_report)
    scan = dict(source_scan) if source_scan is not None else verify_no_holdout_access()
    if scan.get("result") != "PASS":
        raise HybridRouterSpecError("the generator self source scan did not pass")
    library = _strip_private(list(formulas) if formulas is not None else build_formulas())
    spec: dict[str, Any] = {
        "schema": SPEC_SCHEMA,
        "issue": ISSUE,
        "kind": KIND,
        "title": (
            "Hybrid preflop response router: route sources, runtime contract and TRAIN-only "
            "preregistration procedure"
        ),
        "status": STATUS,
        "frozen": True,
        "authored_before_validation_read": True,
        "terminal_evaluation_reads": 0,
        "purpose": (
            "preregister, before any closure evaluation, how a preflop response request is routed "
            "between the active strong-support model, the generalized sparse in-domain channel and "
            "a fail-closed abstention, and how every admission threshold is derived from TRAIN-only "
            "out-of-fold evidence"
        ),
        "split_policy": {
            "allowed_splits": list(ALLOWED_SPLITS),
            "consumed_splits": list(resolved_splits),
            "refused_splits": list(REFUSED_SPLITS),
            "fail_closed_on_refused_split": True,
            "refused_split_is_a_hard_error": True,
            "statement": (
                "the freeze consumes TRAIN only; requiring any VALIDATION or TEST split raises a "
                "hard error before a single byte of the spec is written"
            ),
        },
        "route_sources": route_sources_block(),
        "route_decision_table": route_decision_table_block(),
        "signals": signals_block(evidence_report),
        "reason_codes": reason_codes_block(),
        "runtime_contract": runtime_contract_block(),
        "strata": strata_block(),
        "ood_gate": ood_gate_block(),
        "procedure": {
            "preregistered": True,
            "registered_before_evaluation": True,
            "evaluation_basis": "TRAIN_only_hand_grouped_out_of_fold",
            "consumed_splits": list(resolved_splits),
            "validation_consumed": False,
            "test_consumed": False,
            "terminal_values_persisted": False,
            "constants": preregistered_constants(),
            "derivation_order": [
                "STRATUM_ASSIGNMENT",
                "OOD_ABSTENTION_CRITERION",
                "ROUTE_SELECTION_PROCEDURE",
                "SUPPORT_STATE_ASSIGNMENT",
                "GLOBAL_NON_INFERIORITY_MARGIN",
                "GLOBAL_NON_INFERIORITY_ANALYTIC_CROSS_CHECK",
                "SPARSE_GAIN_FLOOR",
                "SPARSE_GAIN_FLOOR_PAIRED_LOWER_BOUND",
                "SPARSE_ECE_MEASUREMENT",
                "SPARSE_ECE_CEILING",
                "FREQUENT_EXACT_NON_DEGRADATION_BOUND",
            ],
            "formulas": library,
        },
        "evidence_bindings": [
            {
                "role": "train_out_of_fold_cv_report",
                "path": CV_REPORT_LOGICAL_PATH,
                "sha256": sha256_file(CV_REPORT_PATH),
            },
            {
                "role": "ood_gate_contract_schema",
                "path": OOD_GATE_SCHEMA_LOGICAL_PATH,
                "sha256": sha256_file(OOD_GATE_SCHEMA_PATH),
            },
            {
                "role": "ood_gate_model_module",
                "path": MODEL_MODULE_LOGICAL_PATH,
                "sha256": sha256_file(MODEL_MODULE_PATH),
            },
            {
                "role": "strata_definition_module",
                "path": CV_MODULE_LOGICAL_PATH,
                "sha256": sha256_file(CV_MODULE_PATH),
            },
            {
                "role": "spec_generator",
                "path": GENERATOR_LOGICAL_PATH,
                "sha256": sha256_file(SOURCE_PATH),
            },
        ],
        "assertions": {
            "train_only": True,
            "validation_consumed": False,
            "test_consumed": False,
            "byte_stable": True,
            "generator_self_source_scan": "PASS",
            "terminal_numeric_values_persisted": False,
        },
    }
    spec["canonical_payload_sha256"] = stable_hash(_canonical_payload(spec))
    return spec


def _canonical_payload(spec: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in spec.items() if key != "canonical_payload_sha256"}


def serialize(spec: Mapping[str, Any]) -> bytes:
    return (json.dumps(spec, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def spec_digest(spec: Mapping[str, Any]) -> str:
    return sha256_bytes(serialize(spec))


def sidecar_text(spec: Mapping[str, Any]) -> str:
    return (
        f"{spec_digest(spec)}  {SPEC_NAME}\n"
        f"# canonical_payload_sha256 {stable_hash(_canonical_payload(spec))}\n"
    )


def write_spec(spec: Mapping[str, Any] | None = None) -> str:
    resolved = dict(spec) if spec is not None else build_spec()
    HERE.mkdir(parents=True, exist_ok=True)
    SPEC_PATH.write_bytes(serialize(resolved))
    DIGEST_PATH.write_text(sidecar_text(resolved), encoding="utf-8")
    return spec_digest(resolved)


def check() -> list[str]:
    problems: list[str] = []
    if not SPEC_PATH.exists():
        return [f"missing {_relative(SPEC_PATH)}"]
    if not DIGEST_PATH.exists():
        return [f"missing {_relative(DIGEST_PATH)}"]
    persisted = SPEC_PATH.read_bytes()
    expected = serialize(build_spec())
    if persisted != expected:
        problems.append("persisted spec bytes diverge from a fresh TRAIN-only rebuild")
    expected_digest = sha256_bytes(expected)
    sidecar = DIGEST_PATH.read_text(encoding="utf-8").splitlines()
    if not sidecar or sidecar[0].split()[0] != expected_digest:
        problems.append("spec .sha256 sidecar mismatch")
    if len(sidecar) > 1 and sidecar[1].startswith("# canonical_payload_sha256"):
        canonical = sidecar[1].split()[-1]
        if canonical != stable_hash(_canonical_payload(build_spec())):
            problems.append("canonical payload digest mismatch")
    return problems


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="verify the persisted spec and sidecar")
    parser.add_argument(
        "--self-check",
        action="store_true",
        help="print the TRAIN-only formula evaluation (never persisted)",
    )
    args = parser.parse_args(argv)
    if args.self_check:
        evaluation = evaluate_train_only(load_train_cv_report())
        print(json.dumps(evaluation, sort_keys=True, indent=2))
        return 0
    if args.check:
        problems = check()
        for problem in problems:
            print(problem, file=sys.stderr)
        return 1 if problems else 0
    digest = write_spec()
    print(f"{digest}  {SPEC_NAME}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

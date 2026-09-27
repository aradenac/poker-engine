#!/usr/bin/env python3
"""#423 -> #367 preflight: one direct router query per visited decision, no EV.

This command walks the scenario #321 adverse response tree -- the 38 required
nodes of the frozen #388 exact tree plus its 7 unresolved raise-sizing frontiers
-- and queries the #423 **T7** hybrid runtime provider
(``tools.preflop.hybrid_response_runtime``) *directly at the exact public
context* of every visited decision.  For every decision it records:

* the ``route_source`` the router chose (``ACTIVE_STRONG_SUPPORT``,
  ``GENERALIZED_SPARSE_IN_DOMAIN`` or ``OOD_ABSTAIN``);
* the exact ``requested_context`` (public frozen fields only);
* the legal-action ``distribution`` of the answering channel;
* the ``support`` bundle (support state, exact support, single-feature support
  shares, the numeric axis domains and the calibrated thresholds);
* the ``uncertainty`` level (``NONE`` / ``HIGH``);
* the frozen ``ood_status`` of the #421 gate and its hard/soft reason codes;
* the ``sizing_source`` -- the conditional raise-sizing provenance the runtime
  declares for a raise at that exact context (never a neighbouring price).

It is a *preflight*: it never runs the #367 Hero EV runner, never computes a
rollout, an EV or a recommendation, never consumes the TEST split and never
mutates an active model pointer.

Admission conditioning
----------------------

The terminal TRAIN-only router report
(``analysis/issue423_hybrid_router/TRAIN_CV_ROUTER_REPORT.json``) is read here
as *evidence*, never re-derived.  Its ``outcome`` is mechanised from the frozen
criteria: ``ADMIT_HYBRID_ROUTER_FOR_ANALYSIS`` iff every frozen criterion
passes, otherwise ``RETAIN_REFERENCE_HYBRID_INSUFFICIENT``.  The walkthrough is
executed and recorded **either way**; when the outcome retains the active
reference the document states the blocking abstention and quotes the frozen
outcome rule verbatim, wires no provider into #367 and computes no Hero EV.

``issue367_preflight_passed``
-----------------------------

The gate is derived mechanically from the terminal outcome and the frozen OOD
rule, and nothing else::

    issue367_preflight_passed =
            issue367_authorized                 # terminal ADMIT outcome, all criteria passed
        and walkthrough.analysis_admissible     # frozen OOD rule: no blocking branch
        and walkthrough.preflight_passed        # every decision classified, no substitution

Walkthrough discipline
----------------------

Every visited decision is either ``DIRECT_EVAL`` (the router answered at the
exact public context with an ``analysis_admissible`` decision) or
``EXPLICIT_ABSTAIN`` (the frozen OOD gate abstained, or a channel refused
fail-closed with a stable runtime code).  No third class exists.

A **significant OOD branch** -- a visited required-tree decision whose frozen
gate abstains on a *hard* reason -- is never rescued by a neighbouring price, a
neighbouring context or a representative price: it stays blocking, is recorded
with its hard reason codes and keeps ``analysis_admissible`` false.  Sparse
in-domain branches (the ``GENERALIZED_SPARSE_IN_DOMAIN`` route) are evaluated
through the calibrated generalized channel, exactly as the frozen route table
requires.  Executable probes confirm the refusal: a caller asking for a
nearest-price / nearest-context substitution is refused with the stable code
``NEAREST_NEIGHBOUR_SUBSTITUTION_REFUSED``, and a perturbed request is
recomputed instead of snapped to a neighbour.

Reconstruction rule
-------------------

The frozen #388 tree stores the public stack as a bucket (``GT75_LE125``), not
as a number, while the runtime needs ``effective_stack_bb``.  The preflight uses
the *same* frozen bucket-representative convention the #419/#421 preflights use
(``STACK_BUCKET_REPRESENTATIVE``) and re-derives the in-bucket alternate to
prove the OOD node labels (and therefore the context identity) are
bucket-invariant.  Only public, frozen fields are consumed: the actor's own
pre-action contribution is the public ``faced raise-to - to_call`` and the faced
raise-to is carried as ``faced_target_total_bb`` so it is never mistaken for a
queried sizing.

Reproduce: ``python3 tools/simulation/issue423_issue367_preflight.py``
Verify:    ``python3 tools/simulation/issue423_issue367_preflight.py --check``
"""
from __future__ import annotations

import argparse
import ast
import contextlib
import hashlib
import json
import math
import pathlib
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.preflop import generalized_response_model as model  # noqa: E402
from tools.preflop import hybrid_response_router as router  # noqa: E402
from tools.preflop import hybrid_response_runtime as runtime_provider  # noqa: E402
from tools.training.fit_model_a_preflop_sizing_hierarchical import (  # noqa: E402
    STACK_BUCKET_ALTERNATES,
    STACK_BUCKET_REPRESENTATIVE,
)

SCHEMA = "poker-issue423-issue367-preflight/v1"
KIND = "ISSUE367_PREFLIGHT"
ISSUE = 423
SOURCE_ISSUE = 367
SCENARIO_ISSUE = 321
SCENARIO_ID = "kts_sb_two_limp_iso4_three_calls_v1"
ROOT_PATH = ["SB:ISO@5"]
INITIAL_ISO_TARGET_TOTAL_BB = 5.0
REQUIRED_NODE_COUNT = 38
UNRESOLVED_FRONTIER_COUNT = 7
UNRESOLVED_FRONTIER_STATE = "UNRESOLVED"

#: The pinned #423 module surface this preflight consumes.
SPEC_PATH = ROOT / "analysis/issue423_hybrid_router/HYBRID_ROUTER_SPEC.json"
SPEC_SIDECAR = ROOT / "analysis/issue423_hybrid_router/HYBRID_ROUTER_SPEC.sha256"
SPEC_SCHEMA = "poker-hybrid-router-spec/v1"
MANIFEST_PATH = ROOT / "analysis/issue423_hybrid_router/ROUTER_MANIFEST.json"
MANIFEST_SIDECAR = ROOT / "analysis/issue423_hybrid_router/ROUTER_MANIFEST.sha256"
MANIFEST_SCHEMA = "poker-hybrid-router-criteria-manifest/v1"
TERMINAL_REPORT_PATH = ROOT / "analysis/issue423_hybrid_router/TRAIN_CV_ROUTER_REPORT.json"
TERMINAL_REPORT_SIDECAR = (
    ROOT / "analysis/issue423_hybrid_router/TRAIN_CV_ROUTER_REPORT.sha256"
)
TERMINAL_REPORT_SCHEMA = "poker-hybrid-router-train-cv-terminal-report/v1"
CALIBRATION_REPORT_PATH = (
    ROOT / "analysis/issue423_hybrid_router/GENERALIZED_CALIBRATION_REPORT.json"
)
CALIBRATION_REPORT_SIDECAR = (
    ROOT / "analysis/issue423_hybrid_router/GENERALIZED_CALIBRATION_REPORT.sha256"
)
CALIBRATION_REPORT_SCHEMA = "poker-generalized-response-calibration-report/v1"

#: The frozen preregistration marker of the #423 spec and criteria.
SPEC_STATUS = "SPEC_ONLY_PREREGISTERED_NOT_ADMITTED"
CRITERIA_STATUS = "FROZEN_BEFORE_TERMINAL_EVALUATION"

SOURCE_PATH = Path(__file__).resolve()
OUTPUT_DIR = ROOT / "analysis/issue423_hybrid_router"
NAME = "ISSUE367_PREFLIGHT.json"
SIDECAR_NAME = "ISSUE367_PREFLIGHT.sha256"

REQUIRED_TREE_PATH = ROOT / "analysis/issue388_exact_tree/REQUIRED_EXACT_TREE.json"
FIXTURE_PATH = ROOT / "tests/fixtures/repro/kts_sb_two_limp_iso4_three_calls.snapshots.json"
RUNTIME_MODULE_PATH = ROOT / "tools/preflop/hybrid_response_runtime.py"
ROUTER_MODULE_PATH = ROOT / "tools/preflop/hybrid_response_router.py"
DATASET_CONTRACT_PATH = ROOT / "contracts/training/generalized-response-dataset.schema.json"
OOD_REPORT_PATH = ROOT / "analysis/issue421_generalized_response/OOD_CALIBRATION_REPORT.json"

#: The frozen #367 admission vocabulary of the #423 terminal report.
ADMITTING_OUTCOME = "ADMIT_HYBRID_ROUTER_FOR_ANALYSIS"
RETAINING_OUTCOME = "RETAIN_REFERENCE_HYBRID_INSUFFICIENT"
TERMINAL_OUTCOMES = (ADMITTING_OUTCOME, RETAINING_OUTCOME)
ISSUE367_RULE_ID = "ISSUE367_CONSUMES_ONLY_AN_ADMITTED_CANDIDATE"

#: The frozen OOD criterion this preflight is derived from.
OOD_CRITERION_ID = "OOD_ABSTENTION_CRITERION"

#: The two -- and only two -- classes a visited decision may fall into.
DIRECT_EVAL = "DIRECT_EVAL"
EXPLICIT_ABSTAIN = "EXPLICIT_ABSTAIN"
DECISION_CLASSES = (DIRECT_EVAL, EXPLICIT_ABSTAIN)

#: Abstention classes of an ``EXPLICIT_ABSTAIN`` decision.
OOD_BRANCH = "OOD_BRANCH"
FAIL_CLOSED_REFUSAL = "FAIL_CLOSED_REFUSAL"

#: Active pointers and frozen evidence that must hash back unchanged after a run.
PROTECTED_FILES = (
    "training/models/preflop_population_model_v5.json",
    "training/models/postflop_population_model_v5.json",
    "training/registry.json",
    "training/populations/registry.json",
    "analysis/issue423_hybrid_router/HYBRID_ROUTER_SPEC.json",
    "analysis/issue423_hybrid_router/ROUTER_MANIFEST.json",
    "analysis/issue423_hybrid_router/GENERALIZED_CALIBRATION_REPORT.json",
    "analysis/issue423_hybrid_router/TRAIN_CV_ROUTER_REPORT.json",
    "analysis/issue388_exact_tree/REQUIRED_EXACT_TREE.json",
    "analysis/issue419_hierarchical_tree/raise_sizing_frontiers_v2/"
    "RAISE_SIZING_FRONTIER_RESOLUTION.json",
    "tests/fixtures/repro/kts_sb_two_limp_iso4_three_calls.snapshots.json",
)

#: Substitutions that must never resolve a decision on this surface.
SUBSTITUTION_CLASSES = (
    "NEAREST_PRICE",
    "NEAREST_CONTEXT",
    "REPRESENTATIVE_PRICE",
    "LEGAL_MINIMUM_FALLBACK",
    "INTERPOLATED_PRICE",
    "CROSS_KEY_SUPPORT_BORROWING",
)

#: The #367 Hero EV runner and every rollout/EV surface it needs.  This
#: preflight must not import or execute any of them; the names are scanned both
#: statically (AST) and dynamically (``sys.modules``).
HERO_EV_FORBIDDEN_SYMBOLS = (
    "run_issue367_real_iso_ev",
    "Issue367ScientificProvider",
    "Issue367OpponentPolicy",
    "Issue367ProviderError",
    "admitted_model_a_iso_provider",
    "run_hero_preflop_iso",
    "AdaptiveBudget",
    "paired_adaptive_preflop_ev",
    "hero_preflop_iso_runner",
    "full_hand_arena",
    "full_hand_benchmark",
    "preflop_grid_evaluator",
    "paired_preflop_grid_evaluator",
    "evaluate_alternative",
    "materialize_world",
)
HERO_EV_FORBIDDEN_IMPORT_MARKERS = (
    "issue367",
    "real_iso_ev",
    "admitted_model_a_iso_provider",
    "paired_adaptive_preflop_ev",
    "hero_preflop_iso_runner",
    "full_hand_arena",
    "full_hand_benchmark",
    "preflop_grid_evaluator",
)

#: Holdout loaders a preflight must never use.  Mirrors the #421 freeze scan.
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
    "read_dataset_rows",
    "iter_response_rows",
)
DATASET_ROOT = ROOT / "training" / "datasets"
HAND_HISTORY_SUFFIXES = frozenset({"jsonl", "zip", "snapshots"})

#: Every file this preflight is allowed to consume: the frozen public evidence of
#: the scenario, the frozen #423 module surface and the terminal admission
#: evidence.  The build re-checks the observed reads against this list, so
#: nothing else can be pulled in.
ALLOWED_EVIDENCE_PATHS = (
    "analysis/issue388_exact_tree/REQUIRED_EXACT_TREE.json",
    "analysis/issue419_hierarchical_tree/raise_sizing_frontiers_v2/"
    "RAISE_SIZING_FRONTIER_RESOLUTION.json",
    "analysis/issue423_hybrid_router/HYBRID_ROUTER_SPEC.json",
    "analysis/issue423_hybrid_router/HYBRID_ROUTER_SPEC.sha256",
    "analysis/issue423_hybrid_router/ROUTER_MANIFEST.json",
    "analysis/issue423_hybrid_router/ROUTER_MANIFEST.sha256",
    "analysis/issue423_hybrid_router/GENERALIZED_CALIBRATION_REPORT.json",
    "analysis/issue423_hybrid_router/GENERALIZED_CALIBRATION_REPORT.sha256",
    "analysis/issue423_hybrid_router/TRAIN_CV_ROUTER_REPORT.json",
    "analysis/issue423_hybrid_router/TRAIN_CV_ROUTER_REPORT.sha256",
    "analysis/issue421_generalized_response/OOD_CALIBRATION_REPORT.json",
    "analysis/issue421_generalized_response/CANDIDATE_MANIFEST.json",
    "analysis/issue421_generalized_response/VALIDATION_RESULT.json",
    "analysis/issue421_generalized_response/model/"
    "candidate_hierarchical_empirical_bayes_dirichlet.json",
    "analysis/issue421_generalized_response/model/"
    "candidate_regularized_multinomial_spline.json",
    "training/models/preflop_population_model_v5.json",
    "tests/fixtures/repro/kts_sb_two_limp_iso4_three_calls.snapshots.json",
    "contracts/training/generalized-response-dataset.schema.json",
    "tools/preflop/generalized_response_model.py",
    "tools/preflop/generalized_response_runtime.py",
    "tools/preflop/hybrid_response_runtime.py",
    "tools/preflop/hybrid_response_router.py",
    "tools/simulation/issue423_issue367_preflight.py",
)

FROZEN_RULE_TEXT = "abstain(c) iff reasons(c) intersect OOD_HARD_REASONS is not empty"


class PreflightError(RuntimeError):
    """Raised when the #367 preflight cannot be produced safely."""


# ---------------------------------------------------------------------------
# small shared helpers
# ---------------------------------------------------------------------------


def serialize(payload: Any) -> bytes:
    return (json.dumps(payload, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def canonical_sha256(value: Any) -> str:
    raw = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: Path | str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _load(path: Path | str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _relative(path: Path | str) -> str:
    try:
        return str(Path(path).resolve().relative_to(ROOT))
    except ValueError:  # pragma: no cover - defensive
        return str(path)


def _is_hand_history_path(raw: str | Path) -> bool:
    """A hand-history archive, a JSONL/zip dataset or anything under training/datasets.

    A `*.snapshots.json` file is hand-history-shaped unless it is one of the
    declared frozen evidence files (the canonical #321 scenario fixture is).
    """
    path = Path(raw)
    name = path.name.lower()
    suffix = path.suffix.lstrip(".").lower()
    if suffix in HAND_HISTORY_SUFFIXES:
        return True
    if name.endswith(".snapshots.json") and _relative(path) not in set(ALLOWED_EVIDENCE_PATHS):
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
            raise PreflightError(f"hand-history/dataset file opened by the preflight: {self}")
        opened.append(_relative(self))
        return original_open(self, *args, **kwargs)

    pathlib.Path.open = guarded_open
    try:
        yield opened
    finally:
        pathlib.Path.open = original_open


def protected_hashes() -> dict[str, str]:
    return {path: sha256_file(ROOT / path) for path in PROTECTED_FILES}


def _scan_symbols(source: str) -> tuple[set[str], list[str]]:
    module = ast.parse(source)
    used: set[str] = set()
    imported: list[str] = []
    for node in ast.walk(module):
        if isinstance(node, ast.Name):
            used.add(node.id)
        elif isinstance(node, ast.Attribute):
            used.add(node.attr)
        elif isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
            used.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
            imported.extend(alias.name for alias in node.names)
            used.update(alias.name for alias in node.names)
    return used, imported


def verify_no_holdout_access(source: str | None = None) -> dict[str, Any]:
    """Static proof that this command uses no holdout loader and no holdout path."""
    text = SOURCE_PATH.read_text(encoding="utf-8") if source is None else source
    used, imported = _scan_symbols(text)
    hits = sorted(used & set(HOLDOUT_LOADER_SYMBOLS))
    if hits:
        raise PreflightError(f"holdout loader symbol used by the preflight: {hits}")
    bad_imports = sorted(
        name
        for name in imported
        if any(marker in name.lower() for marker in ("validation", "holdout"))
    )
    if bad_imports:
        raise PreflightError(f"holdout-looking import in the preflight: {bad_imports}")
    return {
        "check": "self_source_scan_for_holdout_loaders",
        "result": "PASS",
        "forbidden_symbols": list(HOLDOUT_LOADER_SYMBOLS),
        "hits": [],
        "holdout_looking_imports": [],
        "detail": (
            "AST scan: the preflight consumes no VALIDATION/TEST loader, imports no "
            "validation/holdout module and opens no hand history; the published TRAIN-only "
            "terminal router report is read as admission evidence, not as a split"
        ),
    }


def verify_no_hero_ev_execution(source: str | None = None) -> dict[str, Any]:
    """Static proof that this command cannot execute the #367 Hero EV runner."""
    text = SOURCE_PATH.read_text(encoding="utf-8") if source is None else source
    used, imported = _scan_symbols(text)
    hits = sorted(used & set(HERO_EV_FORBIDDEN_SYMBOLS))
    if hits:
        raise PreflightError(f"Hero EV symbol used by the preflight: {hits}")
    bad_imports = sorted(
        name
        for name in imported
        if any(marker in name.lower() for marker in HERO_EV_FORBIDDEN_IMPORT_MARKERS)
    )
    if bad_imports:
        raise PreflightError(f"Hero EV module imported by the preflight: {bad_imports}")
    return {
        "check": "self_source_scan_for_hero_ev",
        "result": "PASS",
        "forbidden_symbols": list(HERO_EV_FORBIDDEN_SYMBOLS),
        "forbidden_import_markers": list(HERO_EV_FORBIDDEN_IMPORT_MARKERS),
        "hits": [],
        "forbidden_modules_imported_during_build": [],
        "runner_module_imported_by_preflight": False,
        "hero_ev_executed": False,
        "recommendation_computed": False,
        "rollouts_executed": 0,
        "ev_values_computed": 0,
        "detail": (
            "AST scan: the preflight imports neither the #367 real ISO EV runner nor any "
            "rollout/EV/adaptive-budget module, and the build re-checks that none appeared "
            "in sys.modules while it ran"
        ),
    }


def hero_ev_modules_present() -> list[str]:
    """Loaded modules that name a Hero EV / rollout / adaptive-budget surface.

    The preflight's own module name carries the source-issue number, so it is
    excluded explicitly instead of being mistaken for the #367 runner.
    """
    own = {__name__, __name__.rsplit(".", 1)[-1]}
    return sorted(
        name
        for name in sys.modules
        if name not in own
        and any(marker in name.lower() for marker in HERO_EV_FORBIDDEN_IMPORT_MARKERS)
    )


# ---------------------------------------------------------------------------
# frozen evidence
# ---------------------------------------------------------------------------


def _verify_sidecar(path: Path, sidecar: Path) -> str:
    if not path.is_file():
        raise PreflightError(f"missing frozen artifact: {_relative(path)}")
    if not sidecar.is_file():
        raise PreflightError(f"missing frozen artifact sidecar: {_relative(sidecar)}")
    digest = sha256_file(path)
    recorded = sidecar.read_text(encoding="utf-8").split()[0]
    if recorded != digest:
        raise PreflightError(f"sidecar digest drifted for {_relative(path)}: {recorded} != {digest}")
    return digest


def load_frozen_spec() -> dict[str, Any]:
    """The frozen #423 hybrid-router spec that declares the routes and the rule."""
    digest = _verify_sidecar(SPEC_PATH, SPEC_SIDECAR)
    spec = _load(SPEC_PATH)
    if spec.get("schema") != SPEC_SCHEMA:
        raise PreflightError("unexpected frozen #423 router spec schema")
    if spec.get("frozen") is not True or spec.get("status") != SPEC_STATUS:
        raise PreflightError("the #423 router spec is not frozen before the terminal evaluation")
    if (spec.get("frozen_criteria") or {}).get("status") != CRITERIA_STATUS:
        raise PreflightError("the #423 frozen criteria are not frozen before the terminal evaluation")
    if spec.get("issue") != ISSUE:
        raise PreflightError("the frozen #423 router spec belongs to another issue")
    split_policy = spec.get("split_policy") or {}
    if list(split_policy.get("allowed_splits") or []) != ["TRAIN"]:
        raise PreflightError("the frozen spec must allow TRAIN only")
    if list(split_policy.get("consumed_splits") or []) != ["TRAIN"]:
        raise PreflightError("the frozen spec must consume TRAIN only")
    for refused in ("VALIDATION", "TEST"):
        if refused not in (split_policy.get("refused_splits") or []):
            raise PreflightError(f"the frozen spec must refuse the {refused} split")
    sources = [str((entry or {}).get("id") or "") for entry in spec.get("route_sources") or []]
    if sources != list(router.ROUTE_SOURCES):
        raise PreflightError("the frozen spec route sources disagree with the router module")
    hard = list((spec.get("ood_gate") or {}).get("hard_reason_codes") or [])
    if hard != list(model.OOD_HARD_REASONS):
        raise PreflightError("the frozen spec hard reason codes disagree with the OOD gate")
    contract = spec.get("runtime_contract") or {}
    rule = str(contract.get("analysis_admissibility_rule") or "")
    if "route_source != OOD_ABSTAIN" not in rule:
        raise PreflightError("the frozen runtime contract lost its analysis-admissibility rule")
    sizing_contract = contract.get("sizing_contract") or {}
    if sizing_contract.get("no_nearest_price_substitution") is not True:
        raise PreflightError("the frozen runtime contract must forbid a nearest-price substitution")
    if sizing_contract.get("fail_closed_on_illegal_target") is not True:
        raise PreflightError("the frozen runtime contract must fail closed on an illegal target")
    abstention = contract.get("abstention_contract") or {}
    if (
        abstention.get("route_source") != router.ROUTE_SOURCE_ABSTAIN
        or abstention.get("analysis_admissible") is not False
        or abstention.get("probabilities_present") is not False
        or abstention.get("selected_action_present") is not False
        or abstention.get("reason_codes_present") is not True
    ):
        raise PreflightError("the frozen runtime abstention contract drifted")
    return {"document": spec, "byte_sha256": digest}


def load_frozen_manifest(spec: Mapping[str, Any]) -> dict[str, Any]:
    """The frozen #423 criteria manifest that pins the spec and the OOD criterion."""
    digest = _verify_sidecar(MANIFEST_PATH, MANIFEST_SIDECAR)
    manifest = _load(MANIFEST_PATH)
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise PreflightError("unexpected frozen router manifest schema")
    if manifest.get("status") != CRITERIA_STATUS:
        raise PreflightError("the router manifest is not frozen before the terminal evaluation")
    if (manifest.get("frozen_spec") or {}).get("sha256") != spec["byte_sha256"]:
        raise PreflightError("the frozen manifest does not pin this router spec")
    criteria = (manifest.get("frozen_criteria") or {}).get("criteria") or []
    row = next((item for item in criteria if item.get("id") == OOD_CRITERION_ID), None)
    if row is None:
        raise PreflightError("the frozen manifest lost the OOD abstention criterion")
    if row.get("unit") != "required_abstention_rate_on_synthetic_ood_probes":
        raise PreflightError("the frozen OOD criterion changed unit")
    if float(row.get("value") or 0.0) != 1.0:
        raise PreflightError("the frozen OOD criterion must require a complete abstention")
    if list((manifest.get("split_policy") or {}).get("consumed_splits") or []) != ["TRAIN"]:
        raise PreflightError("the frozen manifest must consume TRAIN only")
    return {"document": manifest, "byte_sha256": digest, "ood_criterion": dict(row)}


def load_calibration_report() -> dict[str, Any]:
    """The frozen #423 T2 calibration report naming the retained sparse channel."""
    digest = _verify_sidecar(CALIBRATION_REPORT_PATH, CALIBRATION_REPORT_SIDECAR)
    report = _load(CALIBRATION_REPORT_PATH)
    if report.get("schema") != CALIBRATION_REPORT_SCHEMA:
        raise PreflightError("unexpected frozen #423 calibration report schema")
    scope = report.get("scope") or {}
    if list(scope.get("consumed_splits") or []) != ["TRAIN"]:
        raise PreflightError("the frozen calibration report must consume TRAIN only")
    if scope.get("test_consumed") or scope.get("validation_consumed"):
        raise PreflightError("the frozen calibration report must report no holdout consumption")
    if report.get("retained_architecture") is None or report.get("retained_method") is None:
        raise PreflightError("the frozen calibration report lost its retained channel identity")
    return {"document": report, "byte_sha256": digest}


def load_terminal_report(spec: Mapping[str, Any]) -> dict[str, Any]:
    """The published, content-addressed terminal TRAIN-only router report."""
    digest = _verify_sidecar(TERMINAL_REPORT_PATH, TERMINAL_REPORT_SIDECAR)
    report = _load(TERMINAL_REPORT_PATH)
    if report.get("schema") != TERMINAL_REPORT_SCHEMA:
        raise PreflightError("unexpected terminal router report schema")
    if report.get("issue") != ISSUE:
        raise PreflightError("the terminal router report belongs to another issue")
    outcome = str(report.get("outcome") or "")
    if outcome not in TERMINAL_OUTCOMES:
        raise PreflightError(f"unknown terminal router outcome: {outcome!r}")
    if (report.get("frozen_spec") or {}).get("sha256") != spec["byte_sha256"]:
        raise PreflightError("the terminal router report was not scored against this frozen spec")
    scope = report.get("scope") or {}
    if list(scope.get("consumed_splits") or []) != ["TRAIN"]:
        raise PreflightError("the terminal router report must be TRAIN-only")
    if scope.get("test_consumed") or scope.get("validation_consumed"):
        raise PreflightError("the terminal router report must report no holdout consumption")
    guards = report.get("guards") or {}
    if guards.get("test_consumed") or guards.get("validation_consumed"):
        raise PreflightError("the terminal router report guards must report no holdout consumption")
    evaluation = report.get("criteria_evaluation") or {}
    if not isinstance(evaluation.get("criteria"), list) or not evaluation.get("criteria"):
        raise PreflightError("the terminal router report carries no criteria evaluation")
    if evaluation.get("all_passed") and outcome != ADMITTING_OUTCOME:
        raise PreflightError("the terminal report refuses admission while every criterion passed")
    if not evaluation.get("all_passed") and outcome != RETAINING_OUTCOME:
        raise PreflightError("the terminal report admits while a frozen criterion failed")
    return {"document": report, "byte_sha256": digest, "outcome": outcome}


def load_required_tree() -> dict[str, Any]:
    tree = _load(REQUIRED_TREE_PATH)
    if tree.get("issue") != 388:
        raise PreflightError("unexpected required-tree issue")
    if tree.get("rules", {}).get("nearest_price") is not False:
        raise PreflightError("the required tree must forbid nearest-price")
    if tree.get("rules", {}).get("nearest_context") is not False:
        raise PreflightError("the required tree must forbid nearest-context")
    if len(tree.get("nodes") or []) != REQUIRED_NODE_COUNT:
        raise PreflightError("the required tree must pin 38 nodes")
    if len(tree.get("unresolved_sizing_frontiers") or []) != UNRESOLVED_FRONTIER_COUNT:
        raise PreflightError("the required tree must pin 7 unresolved raise-sizing frontiers")
    if sha256_file(FIXTURE_PATH) != tree.get("fixture_sha256"):
        raise PreflightError("the canonical #321 fixture is not the one the tree pins")
    fixture = _load(FIXTURE_PATH)
    if fixture.get("scenario_id") != SCENARIO_ID:
        raise PreflightError("unexpected #321 canonical fixture")
    root = next((node for node in tree["nodes"] if node["id"] == tree["root_id"]), None)
    if root is None or list(root["path"]) != ROOT_PATH:
        raise PreflightError("the required tree root is not SB:ISO@5")
    if float(tree["rules"]["initial_iso_target_total_bb"]) != INITIAL_ISO_TARGET_TOTAL_BB:
        raise PreflightError("the required tree initial ISO target drifted")
    return tree


def load_frontiers() -> dict[str, Any]:
    """The frozen v2 raise-sizing frontier resolution of the #388/#419 bundles."""
    if not model.FRONTIER_RESOLUTION_PATH.is_file():
        raise PreflightError("the frozen raise-sizing frontier resolution is unavailable")
    frontiers = _load(model.FRONTIER_RESOLUTION_PATH)
    if frontiers.get("schema") != "poker-raise-sizing-frontier-resolution/v2":
        raise PreflightError("unexpected frozen frontier resolution schema")
    if frontiers.get("scenario_issue") != SCENARIO_ISSUE or frontiers.get("source_issue") != 388:
        raise PreflightError("the frozen frontier resolution belongs to another scenario")
    rows = frontiers.get("frontiers") or []
    if len(rows) != UNRESOLVED_FRONTIER_COUNT:
        raise PreflightError("the frozen frontier resolution must carry 7 frontiers")
    if int(frontiers.get("resolved_count") or 0) != 0:
        raise PreflightError("this preflight pins the unresolved frontier bundle")
    if int(frontiers.get("unresolved_count") or 0) != UNRESOLVED_FRONTIER_COUNT:
        raise PreflightError("the frozen frontier resolution must carry 7 unresolved frontiers")
    for row in rows:
        if row.get("resolution_state") != UNRESOLVED_FRONTIER_STATE:
            raise PreflightError(
                f"frontier {row.get('path')} is not UNRESOLVED; this preflight pins the "
                "unresolved-before-#367 surface"
            )
        if row.get("independent_of_the_response_model") is not True:
            raise PreflightError(
                f"frontier {row.get('path')} is not declared independent of the response model"
            )
    if frontiers.get("split_consumed") != "TRAIN":
        raise PreflightError("the frozen frontier resolution must consume TRAIN only")
    if frontiers.get("test_consumed") or frontiers.get("validation_consumed"):
        raise PreflightError("the frozen frontier resolution must report no holdout consumption")
    frozen_rule = frontiers.get("frozen_rule") or {}
    for forbidden in ("nearest_price", "nearest_context", "target_drift"):
        if frozen_rule.get(forbidden) is not False:
            raise PreflightError(f"the frozen frontier rule must forbid {forbidden}")
    substitutions = frozen_rule.get("substitutions_forbidden") or {}
    for forbidden in ("nearest_price", "nearest_context", "legal_minimum_fallback",
                      "representative_price", "empirical_observed_target", "target_drift"):
        if substitutions.get(forbidden) is not False:
            raise PreflightError(f"the frozen frontier rule must forbid {forbidden}")
    return frontiers


# ---------------------------------------------------------------------------
# admission conditioning
# ---------------------------------------------------------------------------


def terminal_outcome_admits(report: Mapping[str, Any]) -> bool:
    """Feed-forward predicate: the terminal outcome admits #423 for analysis."""
    evaluation = report["document"]["criteria_evaluation"]
    return bool(
        report["outcome"] == ADMITTING_OUTCOME
        and evaluation.get("all_passed") is True
        and not evaluation.get("failed")
    )


def issue367_admission(
    spec: Mapping[str, Any],
    manifest: Mapping[str, Any],
    report: Mapping[str, Any],
) -> dict[str, Any]:
    """Condition the preflight on the terminal outcome of the frozen criteria."""
    evaluation = report["document"]["criteria_evaluation"]
    failed = list(evaluation.get("failed") or [])
    authorized = terminal_outcome_admits(report)
    blocking: list[str] = []
    if not authorized:
        blocking.append(f"terminal router outcome is {report['outcome']}")
        blocking.extend(f"failed frozen criterion: {name}" for name in failed)
        if report["outcome"] != ADMITTING_OUTCOME:
            blocking.append(
                f"no {ADMITTING_OUTCOME} outcome exists for the hybrid router on the frozen criteria"
            )
        else:
            blocking.append("the terminal report does not authorize #367 consumption")
    criteria = evaluation.get("criteria") or []
    passed = sum(1 for row in criteria if row.get("passed"))
    return {
        "kind": "ISSUE367_ADMISSION_CONDITION",
        "rule_id": ISSUE367_RULE_ID,
        "authority": _relative(TERMINAL_REPORT_PATH),
        "authority_byte_sha256": report["byte_sha256"],
        "question": "may the #423 hybrid router be consumed by the #367 Hero EV run?",
        "outcome_rule": evaluation.get("outcome_rule"),
        "outcome_rule_verbatim": (
            f"{ADMITTING_OUTCOME} iff every frozen criterion passes; otherwise "
            f"{RETAINING_OUTCOME}"
        ),
        "admitting_outcome": ADMITTING_OUTCOME,
        "retaining_outcome": RETAINING_OUTCOME,
        "terminal_outcome": report["outcome"],
        "criteria_passed": passed,
        "criteria_total": len(criteria),
        "criteria_failed": failed,
        "criteria_order": list(evaluation.get("criteria_order") or []),
        "evidence_scope": dict(report["document"].get("scope") or {}),
        "issue367_authorized": authorized,
        "authorized_when": [
            "the terminal router report outcome is ADMIT_HYBRID_ROUTER_FOR_ANALYSIS",
            "every frozen #423 admission criterion passed",
            "the walkthrough is fully analysis-admissible (no blocking branch)",
        ],
        "forbidden_while": [
            "the terminal router report outcome is RETAIN_REFERENCE_HYBRID_INSUFFICIENT",
            "a frozen #423 admission criterion failed",
            "a visited decision of the required scenario walk is not analysis-admissible",
        ],
        "consequence_when_forbidden": (
            "the preflight walkthrough is recorded as evidence only; no provider is wired "
            "into #367, no Hero EV is computed and #367 is not launched"
        ),
        "consumption": "AUTHORIZED" if authorized else "FORBIDDEN",
        "outcome": "ADMITTED" if authorized else "ABSTAIN_BLOCKED_ADMISSION",
        "blocking_reasons": blocking,
        "currently_retained_reference": {
            "model_id": runtime_provider.ACTIVE_MODEL_ID,
            "path": _relative(runtime_provider.ACTIVE_MODEL_PATH),
            "sha256": runtime_provider.ACTIVE_MODEL_SHA256,
            "role": "the reference #367 keeps while the hybrid router is not admitted",
        },
        "abstention": (
            None
            if authorized
            else {
                "code": "ISSUE367_ADMISSION_NOT_GRANTED",
                "detail": (
                    "the hybrid router may not be consumed by #367: the preflight records the "
                    "direct router walkthrough as evidence only, wires no provider into #367 "
                    "and computes no Hero EV"
                ),
                "rule_id": ISSUE367_RULE_ID,
                "hero_ev_consumed": False,
                "test_consumed": False,
                "active_model_pointer_mutation": False,
                "promotion_performed": False,
            }
        ),
    }


def ood_rule_record(
    spec: Mapping[str, Any],
    manifest: Mapping[str, Any],
) -> dict[str, Any]:
    """The frozen OOD rule, quoted verbatim and mechanised into a predicate."""
    row = manifest["ood_criterion"]
    contract = spec["document"]["runtime_contract"]
    gate = spec["document"]["ood_gate"]
    return {
        "rule_id": OOD_CRITERION_ID,
        "criterion_verbatim": row.get("criterion"),
        "derivation_rule_verbatim": row.get("derivation_rule"),
        "statement": row.get("justification", {}).get("statement"),
        "mechanised_predicate": FROZEN_RULE_TEXT,
        "abstains_on_hard_reasons_only": True,
        "hard_reason_codes": list(gate.get("hard_reason_codes") or []),
        "soft_reason_codes": list(gate.get("soft_reason_codes") or []),
        "hard_reason_codes_are_decisive": True,
        "soft_reasons_may_only_raise_uncertainty": True,
        "statuses": list(gate.get("statuses") or []),
        "analysis_admissibility_rule": contract.get("analysis_admissibility_rule"),
        "abstention_contract": dict(contract.get("abstention_contract") or {}),
        "required_abstention_rate_on_synthetic_ood_probes": float(row.get("value") or 0.0),
        "declared_probe_kinds": list(
            (row.get("effectifs") or {}).get("declared_probe_kinds") or []
        ),
        "applies_to": (
            "every visited decision of the scenario walkthrough; a hard-reason OOD branch is "
            "blocking and is never substituted by a neighbouring price or context"
        ),
    }


# ---------------------------------------------------------------------------
# context reconstruction (public, frozen fields only)
# ---------------------------------------------------------------------------


def _bucket_representative(bucket: str) -> tuple[float, float]:
    if bucket not in STACK_BUCKET_REPRESENTATIVE:
        raise PreflightError(f"unknown frozen stack bucket: {bucket!r}")
    return STACK_BUCKET_REPRESENTATIVE[bucket], STACK_BUCKET_ALTERNATES[bucket]


def node_request_context(node: Mapping[str, Any]) -> dict[str, Any]:
    """Public response context of one required node, rebuilt from frozen fields only.

    ``target_total_bb`` in the #388 tree is the raise-to the actor *faces*, while
    the response model uses that field for a *queried* sizing.  The faced price is
    therefore carried as ``faced_target_total_bb`` and the queried sizing stays
    ``None`` (the marginal response distribution), and the actor's own
    pre-action contribution is the public ``faced raise-to - to_call``.
    """
    frozen = dict(node["context"])
    bucket = str(frozen["effective_stack_bucket"])
    representative, _alternate = _bucket_representative(bucket)
    faced = float(frozen["target_total_bb"])
    to_call = float(frozen["to_call_bb"])
    context = {key: value for key, value in frozen.items() if key != "effective_stack_bucket"}
    context["effective_stack_bb"] = float(representative)
    context["target_total_bb"] = None
    context["faced_target_total_bb"] = faced
    context["actor_contribution_bb"] = max(faced - to_call, 0.0)
    context["current_bet_bb"] = faced
    return context


def alternate_stack_context(node: Mapping[str, Any]) -> dict[str, Any]:
    """The same node with the in-bucket alternate stack (invariance check only)."""
    context = node_request_context(node)
    bucket = str(node["context"]["effective_stack_bucket"])
    _representative, alternate = _bucket_representative(bucket)
    context["effective_stack_bb"] = float(alternate)
    return context


def frontier_request_context(frontier: Mapping[str, Any], node: Mapping[str, Any]) -> dict[str, Any]:
    """Public context of one frozen raise-sizing frontier.

    Each frozen frontier is the RAISE edge of one required tree node, so the full
    public context is that required node's frozen context plus the frozen engine
    interval.  The frozen interval is authoritative for the raise window (it is
    the engine's own ``min_raise_to``/``max_raise_to`` pair), and the runtime's
    ``raise_sizing_window`` honours it, so the cap never falls back to a derived
    conservative bound.
    """
    context = node_request_context(node)
    interval = frontier.get("legal_target_interval_bb")
    if not interval or len(interval) != 2:
        raise PreflightError(f"frontier {frontier.get('node_id')} has no frozen legal interval")
    context["legal_target_interval_bb"] = [float(interval[0]), float(interval[1])]
    return context


def frontier_context_cross_check(
    frontier: Mapping[str, Any], node: Mapping[str, Any]
) -> dict[str, Any]:
    """How the frontier's structural context agrees with its required node."""
    structural = dict(node["context"])
    frontier_context = dict(frontier.get("structural_context") or {})
    return {
        "rule": (
            "the frontier's structural context is cross-checked against the required node it is "
            "the RAISE edge of; the live position *set* and the ordered public history must agree"
        ),
        "family_agrees": frontier_context.get("family") == structural.get("family"),
        "actor_position_agrees": frontier_context.get("actor_position")
        == structural.get("actor_position"),
        "table_size_agrees": frontier_context.get("table_size") == structural.get("table_size"),
        "raise_level_agrees": frontier_context.get("raise_level")
        == structural.get("raise_level"),
        "live_position_set_agrees": sorted(frontier_context.get("live_positions") or [])
        == sorted(structural.get("live_positions") or []),
        "history_agrees": list(frontier_context.get("history") or [])
        == list(structural.get("history") or []),
        "all_in_position_set_agrees": sorted(frontier_context.get("all_in_positions") or [])
        == sorted(structural.get("all_in_positions") or []),
        "structural_live_positions": list(frontier_context.get("live_positions") or []),
        "required_node_live_positions": list(structural.get("live_positions") or []),
    }


# ---------------------------------------------------------------------------
# provider queries
# ---------------------------------------------------------------------------


FAIL_CLOSED_ERRORS = (
    runtime_provider.HybridResponseRuntimeError,
    model.GeneralizedResponseModelError,
    router.RouterError,
)


def _fail_closed_code(error: BaseException) -> str:
    code = getattr(error, "code", None)
    if code:
        return str(code)
    return type(error).__name__


def _base_query(
    runtime: runtime_provider.HybridResponseRuntime,
    context: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """One direct query, classified as direct-eval or explicit abstention."""
    try:
        document = runtime.resolve(context, strict=False)
    except FAIL_CLOSED_ERRORS as error:
        return None, {"code": _fail_closed_code(error), "message": str(error)}
    return document, None


def _distribution(document: Mapping[str, Any]) -> dict[str, Any]:
    probabilities = document.get("probabilities")
    selected = document.get("selected_action")
    view = None
    selected_probability = None
    if probabilities is not None:
        view = {
            action: float(probabilities[action])
            for action in model.ACTIONS
            if action in probabilities
        }
        if selected in view:
            selected_probability = view[selected]
    return {
        "probabilities": view,
        "probability_sum": document.get("probability_sum"),
        "illegal_mass": document.get("illegal_mass"),
        "legal_actions": list(document.get("legal_actions") or []),
        "masked_actions": list(document.get("masked_actions") or []),
        "selected_action": selected,
        "selected_action_probability": selected_probability,
    }


def _support_view(document: Mapping[str, Any]) -> dict[str, Any]:
    signals = document["signals"]
    detail = signals.get("detail") or {}
    return {
        "support_state": document["support_state"],
        "support_exact": signals.get("support_exact"),
        "support_feature_level": signals.get("support_feature_level"),
        "distance_to_domain": signals.get("distance_to_domain"),
        "feature_in_domain": signals.get("feature_in_domain"),
        "stratum": signals.get("stratum"),
        "exact_context": dict(detail.get("exact_context") or {}),
        "feature_support": dict(detail.get("feature_support") or {}),
        "feature_share": dict(detail.get("feature_share") or {}),
        "axes": {axis: dict(entry) for axis, entry in (detail.get("axes") or {}).items()},
        "thresholds": dict(detail.get("thresholds") or {}),
        "uncertainty_flags": dict(detail.get("uncertainty_flags") or {}),
        "channel_cell": dict((document.get("channel") or {}).get("cell") or {}),
    }


def _ood_status_view(document: Mapping[str, Any]) -> dict[str, Any]:
    signals = document["signals"]
    hard = list(signals.get("hard_reasons") or [])
    soft = list(signals.get("soft_reasons") or [])
    return {
        "status": document["ood_status"],
        "abstains": bool(hard),
        "hard_reasons": hard,
        "soft_reasons": soft,
        "reasons": list(signals.get("reasons") or []),
        "reason_catalog": dict((document.get("reason_codes") or {}).get("catalog") or {}),
        "runtime_reason_codes": list((document.get("reason_codes") or {}).get("runtime") or []),
        "runtime_reason_catalog": dict(
            (document.get("reason_codes") or {}).get("runtime_catalog") or {}
        ),
        "abstaining_reason_codes": list(
            (document.get("reason_codes") or {}).get("abstaining") or []
        ),
        "frozen_rule_id": OOD_CRITERION_ID,
        "analysis_admissible": bool(document["analysis_admissible"]),
        "fail_closed_reason": document.get("fail_closed_reason"),
    }


def _conditional_sizing_view(sizing: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """The conditional raise-sizing answer a raise at the queried context declares."""
    if sizing is None:
        return None
    return {
        "schema": sizing.get("schema"),
        "action": sizing.get("action"),
        "status": sizing.get("status"),
        "fail_closed_reason": sizing.get("fail_closed_reason"),
        "support": dict(sizing.get("support") or {}),
        "uncertainty": (
            None if sizing.get("uncertainty") is None else dict(sizing["uncertainty"])
        ),
        "quantiles_bb": dict(sizing.get("quantiles_bb") or {}),
        "generated_count": sizing.get("generated_count"),
        "illegal_count": sizing.get("illegal_count"),
        "nearest_price_substituted": sizing.get("nearest_price_substituted"),
        "nearest_context_substituted": sizing.get("nearest_context_substituted"),
    }


def _sizing_declaration(provenance: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if provenance is None:
        return None
    return {
        "schema": provenance.get("schema"),
        "action": provenance.get("action"),
        "sizing_channel": provenance.get("sizing_channel"),
        "sizing_model_id": provenance.get("sizing_model_id"),
        "sizing_model_hash": provenance.get("sizing_model_hash"),
        "sizing_module": provenance.get("sizing_module"),
        "queried": provenance.get("queried"),
        "queried_target_total_bb": provenance.get("queried_target_total_bb"),
        "target_total_bb": provenance.get("target_total_bb"),
        "conditioning_target_source": provenance.get("conditioning_target_source"),
        "sizing_ratio": provenance.get("sizing_ratio"),
        "legal_window": provenance.get("legal_window"),
        "inside_legal_window": provenance.get("inside_legal_window"),
        "violation": provenance.get("violation"),
        "window_policy": provenance.get("window_policy"),
        "conditional_sizing_status": provenance.get("conditional_sizing_status"),
        "conditional_sizing": _conditional_sizing_view(provenance.get("conditional_sizing")),
        "selected_sizing_bb": provenance.get("selected_sizing_bb"),
        "no_nearest_price_substitution": provenance.get("no_nearest_price_substitution"),
        "nearest_price_substituted": provenance.get("nearest_price_substituted"),
        "nearest_context_substituted": provenance.get("nearest_context_substituted"),
    }


def _channel_answer(document: Mapping[str, Any]) -> dict[str, Any]:
    """The minimal channel answer the runtime's sizing provenance reads."""
    channel = document.get("channel") or {}
    return {
        "route_source": document.get("route_source"),
        "channel": channel.get("channel"),
        "model_id": document.get("model_id"),
        "model_hash": document.get("model_hash"),
        "cell": channel.get("cell"),
    }


def _conditional_raise_source(
    runtime: runtime_provider.HybridResponseRuntime,
    context: Mapping[str, Any],
    document: Mapping[str, Any],
) -> dict[str, Any]:
    """The sizing source a RAISE at this exact context declares (never a neighbour).

    The hybrid runtime conditions an aggressive answer on the queried target when
    the caller supplied one, and otherwise on the sizing channel's own verified
    answer.  The marginal walkthrough queries no sizing, so this records the
    *declared* sizing source of the raise branch: the channel identity, the
    conditioning-target source and the engine's legal window verdict.  It never
    substitutes a neighbouring price.
    """
    answer = _channel_answer(document)
    try:
        provenance = runtime.sizing_provenance(context, answer=answer, selected_action="RAISE")
    except FAIL_CLOSED_ERRORS as error:  # pragma: no cover - defensive
        return {"available": False, "reason": _fail_closed_code(error), "declaration": None}
    return {
        "available": provenance is not None,
        "reason": None if provenance is not None else "NO_CONDITIONAL_SIZING_CHANNEL",
        "declaration": _sizing_declaration(provenance),
    }


def _sizing_source_view(
    runtime: runtime_provider.HybridResponseRuntime,
    context: Mapping[str, Any],
    document: Mapping[str, Any],
) -> dict[str, Any]:
    declared = _sizing_declaration(document.get("sizing_provenance"))
    conditional = _conditional_raise_source(runtime, context, document)
    conditional_declaration = conditional.get("declaration") or {}
    return {
        "source": "SIZING_PROVENANCE" if declared else "NO_AGGRESSIVE_SELECTION",
        "selected_action": document.get("selected_action"),
        "selected_sizing_bb": document.get("selected_sizing_bb"),
        "sizing_channel": (
            declared["sizing_channel"] if declared else conditional_declaration.get("sizing_channel")
        ),
        "conditioning_target_source": (
            declared["conditioning_target_source"]
            if declared
            else conditional_declaration.get("conditioning_target_source")
        ),
        "declared_on_the_decision": declared,
        "conditional_raise": conditional,
        "nearest_price_substituted": False,
        "legal_minimum_fallback_substituted": False,
        "representative_price_substituted": False,
    }


def _decision_view(document: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema": document["schema"],
        "contract_schema": document["contract_schema"],
        "status": document["status"],
        "usable": document["usable"],
        "abstain": document["abstain"],
        "analysis_admissible": document["analysis_admissible"],
        "context_key": document["context_key"],
        "route_source": document["route_source"],
        "routed_source": document["routed_source"],
        "support_state": document["support_state"],
        "uncertainty": document["uncertainty"],
        "ood_status": document["ood_status"],
        "stratum": document["stratum"],
        "model_id": document["model_id"],
        "model_hash": document["model_hash"],
        "fail_closed_reason": document["fail_closed_reason"],
        "no_nearest_price_substitution": document["no_nearest_price_substitution"],
        "no_nearest_context_substitution": document["no_nearest_context_substitution"],
        "nearest_price_substituted": document["nearest_price_substituted"],
        "nearest_context_substituted": document["nearest_context_substituted"],
        "request": dict(document["request"]),
        "routing_rule": dict((document.get("routing") or {}).get("rule") or {}),
        "deterministic_seed": document["deterministic_seed"],
        "decision_canonical_sha256": document["decision_canonical_sha256"],
    }


def _abstention_view(
    document: Mapping[str, Any] | None,
    error: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if document is None:
        hard: list[str] = []
        return {
            "code": (error or {}).get("code"),
            "message": (error or {}).get("message"),
            "class": FAIL_CLOSED_REFUSAL,
            "route_source": None,
            "hard_reasons": hard,
            "soft_reasons": [],
            "selected_action": None,
            "sizing": None,
        }
    signals = document["signals"]
    hard = list(signals.get("hard_reasons") or [])
    soft = list(signals.get("soft_reasons") or [])
    return {
        "code": document.get("fail_closed_reason") or (OOD_CRITERION_ID if hard else None),
        "message": (
            "the frozen OOD gate abstained for this context"
            if hard
            else "a channel refused fail-closed at this context"
        ),
        "class": OOD_BRANCH if hard else FAIL_CLOSED_REFUSAL,
        "route_source": document.get("route_source"),
        "routed_source": document.get("routed_source"),
        "hard_reasons": hard,
        "soft_reasons": soft,
        "selected_action": None,
        "sizing": None,
    }


def node_record(
    index: int,
    node: Mapping[str, Any],
    runtime: runtime_provider.HybridResponseRuntime,
) -> dict[str, Any]:
    frozen = dict(node["context"])
    bucket = str(frozen["effective_stack_bucket"])
    representative, alternate = _bucket_representative(bucket)
    context = node_request_context(node)
    alternate_context = alternate_stack_context(node)
    base_key = model.ood_exact_context_key(context)
    alternate_key = model.ood_exact_context_key(alternate_context)

    document, abstention = _base_query(runtime, context)
    structural_actions = sorted({str(edge["action"]) for edge in node.get("edges") or []})
    record: dict[str, Any] = {
        "index": index,
        "node_identity": {
            "node_id": node["id"],
            "path": list(node["path"]),
            "audit_exact_key": node["audit_exact_key"],
            "runtime_support_context_key": node["runtime_support_context_key"],
            "runtime_exact_preflop_node_key": node["runtime_exact_preflop_node_key"],
            "family": frozen.get("family"),
            "actor_position": frozen.get("actor_position"),
            "aggressor_position": frozen.get("aggressor_position"),
            "table_size": frozen.get("table_size"),
            "raise_level": frozen.get("raise_level"),
            "live_positions": list(frozen.get("live_positions") or []),
            "all_in_positions": list(frozen.get("all_in_positions") or []),
            "structural_actions": structural_actions,
            "structural_actions_outside_the_response_action_space": sorted(
                action for action in structural_actions if action not in model.ACTIONS
            ),
        },
        "requested_context": frozen,
        "faced_target_total_bb": float(frozen["target_total_bb"]),
        "actor_contribution_bb": context["actor_contribution_bb"],
        "stack_reconstruction": {
            "bucket": bucket,
            "representative_bb": representative,
            "alternate_bb": alternate,
            "representative_source": (
                "frozen #388 public stack bucket via the #419 "
                "STACK_BUCKET_REPRESENTATIVE convention"
            ),
            "representative_context_key": base_key,
            "alternate_context_key": alternate_key,
            "ood_feature_key_invariant": base_key == alternate_key,
        },
    }
    if document is None:
        view = _abstention_view(None, abstention)
        record.update(
            {
                "decision_class": EXPLICIT_ABSTAIN,
                "abstention": view,
                "route_source": None,
                "distribution": None,
                "support": None,
                "uncertainty": None,
                "ood_status": {
                    "status": None,
                    "abstains": view["class"] == OOD_BRANCH,
                    "hard_reasons": view["hard_reasons"],
                    "soft_reasons": [],
                    "frozen_rule_id": OOD_CRITERION_ID,
                    "analysis_admissible": False,
                    "fail_closed_reason": view["code"],
                },
                "sizing_source": None,
                "decision": None,
            }
        )
        return record

    decision = _decision_view(document)
    ood = _ood_status_view(document)
    record.update(
        {
            "decision_class": DIRECT_EVAL if document["analysis_admissible"] else EXPLICIT_ABSTAIN,
            "abstention": None if document["analysis_admissible"] else _abstention_view(document, None),
            "route_source": document["route_source"],
            "distribution": _distribution(document),
            "support": _support_view(document),
            "uncertainty": document["uncertainty"],
            "ood_status": ood,
            "sizing_source": _sizing_source_view(runtime, context, document),
            "decision": decision,
        }
    )
    return record


def frontier_record(
    index: int,
    frontier: Mapping[str, Any],
    node: Mapping[str, Any],
    runtime: runtime_provider.HybridResponseRuntime,
) -> dict[str, Any]:
    context = frontier_request_context(frontier, node)
    interval = [float(value) for value in context["legal_target_interval_bb"]]
    document, abstention = _base_query(runtime, context)
    record: dict[str, Any] = {
        "index": index,
        "node_id": frontier.get("node_id"),
        "path": list(frontier.get("path") or []),
        "action": "RAISE",
        "resolution_state": frontier.get("resolution_state"),
        "blocker_reason_code": frontier.get("blocker_reason_code"),
        "blocks_required_tree_complete": bool(frontier.get("blocks_required_tree_complete")),
        "legal_target_interval_bb": interval,
        "requested_context": dict(context),
        "structural_context_cross_check": frontier_context_cross_check(frontier, node),
        "exact_support": dict(frontier.get("exact_support") or {}),
        "coded_reasons": list(frontier.get("coded_reasons") or []),
        "coded_notes": list(frontier.get("coded_notes") or []),
        "train_observed_raise_actions": frontier.get("train_observed_raise_actions"),
        "train_observed_raise_targets": frontier.get("train_observed_raise_targets"),
        "exact_tree_status": UNRESOLVED_FRONTIER_STATE,
        "exact_tree_satisfied": False,
        "independent_of_the_response_model": bool(
            frontier.get("independent_of_the_response_model")
        ),
        "frozen_sizing_source": {
            "sizing_source": None,
            "blocker_reason_code": frontier.get("blocker_reason_code"),
            "expansion_rule": frontier.get("issue388_expansion_rule"),
            "reason": frontier.get("issue388_reason"),
            "nearest_price_substituted": False,
            "nearest_context_substituted": False,
            "representative_price_substituted": False,
            "legal_minimum_fallback_substituted": False,
        },
    }
    if document is None:
        view = _abstention_view(None, abstention)
        record.update(
            {
                "decision_class": EXPLICIT_ABSTAIN,
                "abstention": view,
                "route_source": None,
                "distribution": None,
                "support": None,
                "uncertainty": None,
                "ood_status": {
                    "status": None,
                    "abstains": view["class"] == OOD_BRANCH,
                    "hard_reasons": view["hard_reasons"],
                    "soft_reasons": [],
                    "frozen_rule_id": OOD_CRITERION_ID,
                    "analysis_admissible": False,
                    "fail_closed_reason": view["code"],
                },
                "sizing_source": None,
                "decision": None,
                "derived_window_bb": None,
                "derived_window_matches_frozen_interval": False,
            }
        )
        return record

    decision = _decision_view(document)
    sizing_source = _sizing_source_view(runtime, context, document)
    window = ((sizing_source.get("conditional_raise") or {}).get("declaration") or {}).get(
        "legal_window"
    ) or {}
    floor = window.get("floor_bb")
    cap = window.get("cap_bb")
    matches = bool(
        floor is not None
        and cap is not None
        and math.isclose(float(floor), interval[0], abs_tol=1e-6)
        and math.isclose(float(cap), interval[1], abs_tol=1e-6)
    )
    record.update(
        {
            "decision_class": DIRECT_EVAL if document["analysis_admissible"] else EXPLICIT_ABSTAIN,
            "abstention": None if document["analysis_admissible"] else _abstention_view(document, None),
            "route_source": document["route_source"],
            "distribution": _distribution(document),
            "support": _support_view(document),
            "uncertainty": document["uncertainty"],
            "ood_status": _ood_status_view(document),
            "sizing_source": sizing_source,
            "decision": decision,
            "derived_window_bb": [floor, cap],
            "derived_window_matches_frozen_interval": matches,
            "window_bounds_source": window.get("bounds_source"),
        }
    )
    return record


# ---------------------------------------------------------------------------
# audits
# ---------------------------------------------------------------------------


def substitution_refusal_probe(
    runtime: runtime_provider.HybridResponseRuntime,
) -> dict[str, Any]:
    """The negative proof: a caller asking for a neighbour is refused, fail-closed."""
    context = node_request_context(
        {
            "context": {
                "family": "VS_ISO",
                "actor_position": "BB",
                "aggressor_position": "SB",
                "caller_count": 0,
                "limper_count": 2,
                "raise_level": 1,
                "table_size": 6,
                "live_positions": ["BB", "BTN", "CO", "SB"],
                "all_in_positions": [],
                "target_total_bb": 5.0,
                "to_call_bb": 4.0,
                "pot_before_bb": 8.0,
                "effective_stack_bucket": "GT75_LE125",
                "history": [],
            }
        }
    )
    attempts: list[dict[str, Any]] = []
    for key in runtime_provider.SUBSTITUTION_REQUEST_KEYS:
        probe = dict(context)
        probe[key] = True
        try:
            runtime.resolve(probe, strict=False)
            attempts.append({"request_key": key, "refused": False, "code": None})
        except runtime_provider.HybridResponseRuntimeError as error:
            attempts.append(
                {
                    "request_key": key,
                    "refused": True,
                    "code": error.code,
                    "refused_before_any_decision": True,
                }
            )
    passed = bool(attempts) and all(
        row["refused"]
        and row["code"] == runtime_provider.FAIL_CLOSED_NEIGHBOUR_SUBSTITUTION
        for row in attempts
    )
    return {
        "probe": "NEIGHBOUR_SUBSTITUTION_REQUEST_REFUSED",
        "rule": "A_CALLER_ASKING_FOR_A_NEIGHBOUR_IS_REFUSED_FAIL_CLOSED",
        "expected_code": runtime_provider.FAIL_CLOSED_NEIGHBOUR_SUBSTITUTION,
        "attempts": attempts,
        "offered_request_keys": list(runtime_provider.SUBSTITUTION_REQUEST_KEYS),
        "neighbours_refused": sum(1 for row in attempts if row["refused"]),
        "passed": passed,
    }


def nearest_substitution_probes(
    runtime: runtime_provider.HybridResponseRuntime,
    root_node: Mapping[str, Any],
    frontier: Mapping[str, Any],
    frontier_node: Mapping[str, Any],
) -> dict[str, Any]:
    """Executable probes that a changed request is recomputed, never snapped."""
    base = node_request_context(root_node)
    exact = runtime.resolve(base, strict=False)

    shifted = dict(base)
    shifted["to_call_bb"] = float(base["to_call_bb"]) + 0.2
    shifted_document = runtime.resolve(shifted, strict=False)
    price_probe = {
        "probe": "PRICE_RECOMPUTATION",
        "requested": {"to_call_bb": base["to_call_bb"]},
        "perturbed": {"to_call_bb": shifted["to_call_bb"]},
        "requested_decision_class": (
            DIRECT_EVAL if exact["analysis_admissible"] else EXPLICIT_ABSTAIN
        ),
        "perturbed_decision_class": (
            DIRECT_EVAL if shifted_document["analysis_admissible"] else EXPLICIT_ABSTAIN
        ),
        "requested_decision_canonical_sha256": exact["decision_canonical_sha256"],
        "perturbed_decision_canonical_sha256": shifted_document["decision_canonical_sha256"],
        "decision_changed": (
            exact["decision_canonical_sha256"] != shifted_document["decision_canonical_sha256"]
        ),
    }
    price_probe["passed"] = bool(price_probe["decision_changed"])

    other = dict(base)
    other["family"] = "LIMPER_VS_ISO" if base["family"] != "LIMPER_VS_ISO" else "VS_ISO"
    other_document = runtime.resolve(other, strict=False)
    context_probe = {
        "probe": "CONTEXT_RECOMPUTATION",
        "requested": {"family": base["family"]},
        "perturbed": {"family": other["family"]},
        "requested_context_key": exact["context_key"],
        "perturbed_context_key": other_document["context_key"],
        "context_key_changed": exact["context_key"] != other_document["context_key"],
        "decision_changed": (
            exact["decision_canonical_sha256"] != other_document["decision_canonical_sha256"]
        ),
    }
    context_probe["passed"] = bool(
        context_probe["context_key_changed"] and context_probe["decision_changed"]
    )

    frontier_context = frontier_request_context(frontier, frontier_node)
    wide = runtime.resolve(frontier_context, strict=False)
    narrowed_context = dict(frontier_context)
    narrowed_context["legal_target_interval_bb"] = [
        float(frontier_context["legal_target_interval_bb"][0]),
        float(frontier_context["legal_target_interval_bb"][1]) - 10.0,
    ]
    narrowed = runtime.resolve(narrowed_context, strict=False)
    wide_window = _sizing_source_view(runtime, frontier_context, wide)
    narrow_window = _sizing_source_view(runtime, narrowed_context, narrowed)
    wide_legal = ((wide_window.get("conditional_raise") or {}).get("declaration") or {}).get(
        "legal_window"
    )
    narrow_legal = ((narrow_window.get("conditional_raise") or {}).get("declaration") or {}).get(
        "legal_window"
    )
    sizing_probe = {
        "probe": "SIZING_WINDOW_RECOMPUTATION",
        "requested_interval_bb": list(frontier_context["legal_target_interval_bb"]),
        "narrowed_interval_bb": list(narrowed_context["legal_target_interval_bb"]),
        "requested_window_bb": [
            (wide_legal or {}).get("floor_bb"),
            (wide_legal or {}).get("cap_bb"),
        ],
        "narrowed_window_bb": [
            (narrow_legal or {}).get("floor_bb"),
            (narrow_legal or {}).get("cap_bb"),
        ],
        "window_changed": wide_legal != narrow_legal,
        "requested_bounds_source": (wide_legal or {}).get("bounds_source"),
        "narrowed_bounds_source": (narrow_legal or {}).get("bounds_source"),
    }
    sizing_probe["passed"] = bool(
        sizing_probe["window_changed"]
        and (wide_legal or {}).get("cap_bb") == frontier_context["legal_target_interval_bb"][1]
        and (narrow_legal or {}).get("cap_bb") == narrowed_context["legal_target_interval_bb"][1]
    )

    interval = [float(value) for value in frontier_context["legal_target_interval_bb"]]
    queried_target = interval[0] + 0.5
    queried_context = dict(frontier_context)
    queried_context["target_total_bb"] = queried_target
    queried_document = runtime.resolve(queried_context, strict=False)
    try:
        queried_provenance = runtime.sizing_provenance(
            queried_context,
            answer=_channel_answer(queried_document),
            selected_action="RAISE",
        )
    except FAIL_CLOSED_ERRORS as error:  # pragma: no cover - defensive
        queried_provenance = None
        queried_error = _fail_closed_code(error)
    else:
        queried_error = None
    queried_probe = {
        "probe": "EXACT_QUERIED_TARGET_HONOURED",
        "queried_target_total_bb": queried_target,
        "declared_queried_target_total_bb": (
            None if queried_provenance is None else queried_provenance["queried_target_total_bb"]
        ),
        "declared_conditioning_target_bb": (
            None if queried_provenance is None else queried_provenance["target_total_bb"]
        ),
        "declared_queried_flag": (
            None if queried_provenance is None else queried_provenance["queried"]
        ),
        "conditioning_target_source": (
            None if queried_provenance is None else queried_provenance["conditioning_target_source"]
        ),
        "nearest_price_substituted": (
            None if queried_provenance is None else queried_provenance["nearest_price_substituted"]
        ),
        "nearest_context_substituted": (
            None if queried_provenance is None else queried_provenance["nearest_context_substituted"]
        ),
        "refusal": queried_error,
    }
    queried_probe["passed"] = bool(
        queried_provenance is not None
        and queried_provenance["queried"] is True
        and queried_provenance["conditioning_target_source"] == "QUERIED_EXACT"
        and queried_provenance["target_total_bb"] is not None
        and math.isclose(
            float(queried_provenance["target_total_bb"]), queried_target, abs_tol=1e-9
        )
        and queried_provenance["nearest_price_substituted"] is False
        and queried_provenance["nearest_context_substituted"] is False
    )

    active_probe = active_exact_cell_probe(runtime, root_node)

    probes = [price_probe, context_probe, sizing_probe, queried_probe]
    return {
        "rule": "A_CHANGED_REQUEST_IS_RECOMPUTED_NEVER_SNAPPED_TO_A_NEIGHBOUR",
        "substitution_classes_refused": list(SUBSTITUTION_CLASSES),
        "probes": probes,
        "probes_passed": all(probe["passed"] for probe in probes),
        "active_exact_cell_probe": active_probe,
    }


def active_exact_cell_probe(
    runtime: runtime_provider.HybridResponseRuntime,
    root_node: Mapping[str, Any],
) -> dict[str, Any]:
    """The active branch must have an exact cell; the nearest active node is never read."""
    context = node_request_context(root_node)
    document = runtime.resolve(context, strict=False)
    routed = str(document["routed_source"])
    exact_cell = runtime_provider.active_exact_cell(runtime.active_reference, context)
    abstained = (
        routed == router.ROUTE_SOURCE_ACTIVE
        and document["abstain"] is True
        and document["fail_closed_reason"] == runtime_provider.FAIL_CLOSED_ACTIVE_CELL_UNAVAILABLE
    )
    return {
        "probe": "ACTIVE_BRANCH_REQUIRES_AN_EXACT_CELL",
        "context_key": document["context_key"],
        "routed_source": routed,
        "exact_active_cell_present": exact_cell is not None,
        "abstained": document["abstain"],
        "fail_closed_reason": document["fail_closed_reason"],
        "nearest_active_node_not_read": exact_cell is None,
        "passed": bool(exact_cell is None and abstained),
    }


def ood_branch_guard(
    runtime: runtime_provider.HybridResponseRuntime,
    rule: Mapping[str, Any],
) -> dict[str, Any]:
    """Prove the frozen OOD rule is wired: a hard reason abstains, fail-closed.

    The probe contexts are drawn from the criterion's own declared probe kinds
    (``unseen_category``, ``extrapolation_stack``, ``missing_domain_axis``) so a
    significant out-of-domain branch is *blocking* on this surface: it carries
    ``analysis_admissible=false``, no distribution and no sizing, and is never
    rescued by a neighbouring price or context.
    """
    base = {
        "family": "VS_ISO",
        "actor_position": "BB",
        "aggressor_position": "SB",
        "limper_count": 0,
        "caller_count": 0,
        "table_size": 6,
        "live_positions": ["BB", "SB"],
        "all_in_positions": [],
        "raise_level": 1,
        "to_call_bb": 4.0,
        "pot_before_bb": 8.0,
        "effective_stack_bb": 125.0,
        "target_total_bb": None,
    }
    unseen = dict(base)
    unseen["family"] = "OPEN_SHOVE_PREFLIGHT_PROBE"
    extrapolated = dict(base)
    extrapolated["effective_stack_bb"] = 99999.0
    missing_axis = {key: value for key, value in base.items() if key != "effective_stack_bb"}

    probes: list[dict[str, Any]] = []
    for kind, context, expected in (
        ("unseen_category", unseen, "UNSEEN_CATEGORY"),
        ("extrapolation_stack", extrapolated, "EXTRAPOLATION_STACK"),
        ("missing_domain_axis", missing_axis, "MISSING_DOMAIN_AXIS"),
    ):
        document = runtime.resolve(context, strict=False)
        hard = list(document["signals"]["hard_reasons"])
        probes.append(
            {
                "kind": kind,
                "expected_reason": expected,
                "route_source": document["route_source"],
                "ood_status": document["ood_status"],
                "hard_reasons": hard,
                "soft_reasons": list(document["signals"]["soft_reasons"]),
                "abstained": document["abstain"],
                "analysis_admissible": document["analysis_admissible"],
                "distribution_present": document["probabilities"] is not None,
                "selected_action": document["selected_action"],
                "sizing_present": document["sizing_provenance"] is not None,
                "expected_reason_present": expected in hard,
                "nearest_price_substituted": document["nearest_price_substituted"],
                "nearest_context_substituted": document["nearest_context_substituted"],
            }
        )
    passed = all(
        row["abstained"]
        and row["analysis_admissible"] is False
        and row["distribution_present"] is False
        and row["selected_action"] is None
        and row["sizing_present"] is False
        and row["expected_reason_present"]
        and row["route_source"] == router.ROUTE_SOURCE_ABSTAIN
        and row["nearest_price_substituted"] is False
        and row["nearest_context_substituted"] is False
        for row in probes
    )
    return {
        "probe": "OOD_BRANCH_IS_BLOCKING_AND_FAILS_CLOSED",
        "rule_id": rule["rule_id"],
        "mechanised_predicate": rule["mechanised_predicate"],
        "probes": probes,
        "probes_passed": passed,
        "blocking_on_hard_reason_only": True,
        "passed": bool(passed),
    }


def faced_price_mapping_guard(
    runtime: runtime_provider.HybridResponseRuntime,
    nodes: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Show why the faced raise-to is never passed as a queried sizing.

    The frozen #388 tree stores, in ``target_total_bb``, the raise-to the actor
    *faces*, while the frozen dataset contract defines that same field as the
    actor's own RAISE/JAM total contribution (null for FOLD/CALL).  Passing the
    faced price as a queried sizing therefore asks the router and the sizing
    channel about a price the actor never chose; the guard records what that
    misreading would do so the mapping stays auditable instead of silent.
    """
    abstaining: list[dict[str, Any]] = []
    refusal_codes: dict[str, int] = {}
    raised: list[dict[str, Any]] = []
    for node in nodes:
        context = node_request_context(node)
        context["target_total_bb"] = context["faced_target_total_bb"]
        document, error = _base_query(runtime, context)
        if document is not None and not document["abstain"]:
            if document["fail_closed_reason"] is None and document.get("selected_action"):
                raised.append(
                    {
                        "path": list(node["path"]),
                        "selected_action": document["selected_action"],
                        "queried_target_total_bb": context["target_total_bb"],
                        "inside_legal_window": (
                            (document.get("sizing_provenance") or {}).get("inside_legal_window")
                        ),
                    }
                )
            continue
        code = (
            ((document or {}).get("fail_closed_reason"))
            or (error or {}).get("code")
            or "UNKNOWN"
        )
        refusal_codes[str(code)] = refusal_codes.get(str(code), 0) + 1
        abstaining.append(
            {
                "path": list(node["path"]),
                "code": code,
                "hard_reasons": (
                    [] if document is None else list(document["signals"]["hard_reasons"])
                ),
            }
        )
    return {
        "rule": "THE_FACED_RAISE_TO_IS_NEVER_PASSED_AS_A_QUERIED_SIZING",
        "mapping_used": {
            "queried_sizing": None,
            "faced_raise_to": "faced_target_total_bb",
            "authority": (
                "contracts/training/generalized-response-dataset.schema.json defines "
                "target_total_bb as the observed total contribution AFTER the action for "
                "RAISE/JAM (null for FOLD/CALL), i.e. the actor's own sizing"
            ),
        },
        "misreading_would_abstain_count": len(abstaining),
        "misreading_would_abstain_nodes": abstaining,
        "misreading_refusal_codes": dict(sorted(refusal_codes.items())),
        "misreading_would_answer_count": len(raised),
        "misreading_would_answer_nodes": raised,
        "misreading_is_not_used": True,
    }


# ---------------------------------------------------------------------------
# walkthrough roll-up and the mechanical gate
# ---------------------------------------------------------------------------


def walkthrough_rollup(
    nodes: Sequence[Mapping[str, Any]],
    frontiers: Sequence[Mapping[str, Any]],
    substitution: Mapping[str, Any],
    ood_guard: Mapping[str, Any],
) -> dict[str, Any]:
    """Classify every visited decision and roll the walkthrough up fail-closed."""
    visited = list(nodes) + list(frontiers)
    classes = [str(record.get("decision_class")) for record in visited]
    unclassified = sorted({value for value in classes if value not in DECISION_CLASSES})
    direct_eval = classes.count(DIRECT_EVAL)
    explicit_abstain = classes.count(EXPLICIT_ABSTAIN)
    every_classified = bool(visited) and not unclassified and (
        direct_eval + explicit_abstain == len(visited)
    )

    blocking: list[dict[str, Any]] = []
    ood_branches: list[dict[str, Any]] = []
    for label, records in (("node", nodes), ("frontier", frontiers)):
        for record in records:
            if record.get("decision_class") != EXPLICIT_ABSTAIN:
                continue
            abstention = record.get("abstention") or {}
            branch = {
                "kind": label,
                "path": list(record.get("path") or record.get("node_identity", {}).get("path") or []),
                "node_id": (
                    record.get("node_id") or record.get("node_identity", {}).get("node_id")
                ),
                "abstention_class": abstention.get("class"),
                "code": abstention.get("code"),
                "hard_reasons": list(abstention.get("hard_reasons") or []),
                "soft_reasons": list(abstention.get("soft_reasons") or []),
                "blocks_analysis": True,
                "substituted": False,
            }
            blocking.append(branch)
            if branch["abstention_class"] == OOD_BRANCH:
                ood_branches.append(branch)

    analysis_admissible = bool(
        every_classified and not blocking and all(
            (record.get("decision") or {}).get("analysis_admissible") is True
            for record in visited
        )
    )
    preflight_passed = bool(
        every_classified
        and substitution.get("probes_passed") is True
        and substitution.get("active_exact_cell_probe", {}).get("passed") is True
        and ood_guard.get("passed") is True
    )

    def _count(accessor) -> dict[str, int]:
        counts: dict[str, int] = {}
        for record in visited:
            if record.get("decision_class") != DIRECT_EVAL:
                continue
            value = accessor(record)
            if value is None:
                continue
            counts[str(value)] = counts.get(str(value), 0) + 1
        return dict(sorted(counts.items()))

    sizing_sources: dict[str, int] = {}
    for record in visited:
        source = (record.get("sizing_source") or {}).get("conditional_raise") or {}
        declaration = source.get("declaration") or {}
        channel = declaration.get("sizing_channel") or "NONE"
        sizing_sources[str(channel)] = sizing_sources.get(str(channel), 0) + 1

    return {
        "rule": "EVERY_VISITED_DECISION_IS_DIRECT_EVAL_OR_EXPLICIT_ABSTAIN",
        "nodes_visited": len(nodes),
        "sizing_frontiers_visited": len(frontiers),
        "decisions_visited": len(visited),
        "direct_eval_decisions": direct_eval,
        "explicit_abstain_decisions": explicit_abstain,
        "unclassified_decisions": unclassified,
        "every_visited_decision_classified": every_classified,
        "analysis_admissible": analysis_admissible,
        "blocking_branches": blocking,
        "blocking_branch_count": len(blocking),
        "significant_ood_branches": ood_branches,
        "significant_ood_branch_count": len(ood_branches),
        "significant_ood_branch_is_blocking": True,
        "route_source_counts": _count(lambda record: record.get("route_source")),
        "support_state_counts": _count(
            lambda record: (record.get("support") or {}).get("support_state")
        ),
        "stratum_counts": _count(lambda record: (record.get("support") or {}).get("stratum")),
        "uncertainty_counts": _count(lambda record: record.get("uncertainty")),
        "ood_status_counts": _count(
            lambda record: (record.get("ood_status") or {}).get("status")
        ),
        "sizing_source_counts_conditional_raise_channel": dict(sorted(sizing_sources.items())),
        "nearest_substitution_probes_passed": substitution.get("probes_passed") is True,
        "ood_branch_guard_passed": ood_guard.get("passed") is True,
        "preflight_passed": preflight_passed,
    }


def derive_issue367_preflight_passed(
    admission: Mapping[str, Any],
    walkthrough: Mapping[str, Any],
) -> dict[str, Any]:
    """The mechanical gate: the terminal outcome AND the frozen OOD rule.

    ``issue367_preflight_passed`` is true only when the terminal router outcome
    admits the candidate for #367, the walkthrough is analysis-admissible under
    the frozen OOD rule (no blocking branch) and the structural preflight passed
    (every decision classified, no neighbour substituted).
    """
    admitted = admission.get("issue367_authorized") is True
    analysis_admissible = walkthrough.get("analysis_admissible") is True
    preflight_passed = walkthrough.get("preflight_passed") is True
    terms = {
        "terminal_outcome_admits": admitted,
        "analysis_admissible": analysis_admissible,
        "preflight_passed": preflight_passed,
    }
    passed = bool(admitted and analysis_admissible and preflight_passed)
    return {
        "formula": (
            "issue367_preflight_passed = terminal_outcome_admits and analysis_admissible "
            "and preflight_passed"
        ),
        "inputs": {
            "terminal_outcome": admission.get("terminal_outcome"),
            "admitting_outcome": admission.get("admitting_outcome"),
            "criteria_failed": list(admission.get("criteria_failed") or []),
            "ood_rule_id": OOD_CRITERION_ID,
            "direct_eval_decisions": walkthrough.get("direct_eval_decisions"),
            "explicit_abstain_decisions": walkthrough.get("explicit_abstain_decisions"),
            "blocking_branch_count": walkthrough.get("blocking_branch_count"),
            "significant_ood_branch_count": walkthrough.get("significant_ood_branch_count"),
            "nearest_substitution_probes_passed": walkthrough.get(
                "nearest_substitution_probes_passed"
            ),
            "ood_branch_guard_passed": walkthrough.get("ood_branch_guard_passed"),
        },
        "terms": terms,
        "issue367_preflight_passed": passed,
    }


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------


def build() -> tuple[dict[str, Any], list[str]]:
    # The provider memoises its registries; drop them so every build re-reads
    # the frozen evidence the same way on a cold process.  This keeps the
    # recorded read set -- and therefore the whole document -- byte-stable
    # across repeated in-process builds.
    runtime_provider.clear_runtime_caches()
    holdout_scan = verify_no_holdout_access()
    hero_ev_scan = verify_no_hero_ev_execution()
    protected_before = protected_hashes()
    hero_ev_modules_before = set(hero_ev_modules_present())

    with hand_history_tripwire() as opened:
        spec = load_frozen_spec()
        manifest = load_frozen_manifest(spec)
        calibration = load_calibration_report()
        report = load_terminal_report(spec)
        tree = load_required_tree()
        frontiers = load_frontiers()
        runtime = runtime_provider.load_runtime(None, None, None, None)
        admission = issue367_admission(spec, manifest, report)
        rule = ood_rule_record(spec, manifest)

        tree_nodes = {str(node["id"]): node for node in tree["nodes"]}
        nodes = [
            node_record(index, node, runtime) for index, node in enumerate(tree["nodes"])
        ]
        frontier_records = [
            frontier_record(
                index,
                frontier,
                tree_nodes[str(frontier.get("node_id"))],
                runtime,
            )
            for index, frontier in enumerate(frontiers["frontiers"])
        ]

        root_node = tree_nodes[str(tree["root_id"])]
        first_frontier = frontiers["frontiers"][0]
        substitution = nearest_substitution_probes(
            runtime,
            root_node,
            first_frontier,
            tree_nodes[str(first_frontier["node_id"])],
        )
        substitution["request_refusal_probe"] = substitution_refusal_probe(runtime)
        substitution["probes_passed"] = bool(
            substitution["probes_passed"]
            and substitution["request_refusal_probe"]["passed"]
        )
        ood_guard = ood_branch_guard(runtime, rule)
        mapping_guard = faced_price_mapping_guard(runtime, tree["nodes"])
        runtime_metadata = runtime.metadata()
        runtime_audit = runtime.audit()

    hero_ev_modules_during_build = sorted(set(hero_ev_modules_present()) - hero_ev_modules_before)
    if hero_ev_modules_during_build:
        raise PreflightError(
            f"Hero EV module imported while the preflight ran: {hero_ev_modules_during_build}"
        )
    hero_ev_scan["forbidden_modules_imported_during_build"] = hero_ev_modules_during_build
    hero_ev_scan["runner_module_imported_by_preflight"] = False
    protected_after = protected_hashes()
    if protected_before != protected_after:
        raise PreflightError("an active registry, model or frozen artifact was mutated")

    observed_reads = sorted(set(opened))
    undeclared_reads = sorted(
        path for path in observed_reads if path not in set(ALLOWED_EVIDENCE_PATHS)
    )
    if undeclared_reads:
        raise PreflightError(
            f"the preflight opened a file outside its declared frozen evidence: {undeclared_reads}"
        )
    hand_history_reads = sorted(
        path for path in observed_reads if _is_hand_history_path(ROOT / path)
    )
    if hand_history_reads:
        raise PreflightError(f"the preflight opened hand history: {hand_history_reads}")

    walkthrough = walkthrough_rollup(nodes, frontier_records, substitution, ood_guard)
    if not walkthrough["every_visited_decision_classified"]:
        raise PreflightError("a visited decision was neither direct-evaluated nor abstained")
    if not substitution["probes_passed"]:
        raise PreflightError("a nearest-substitution probe failed")
    if not substitution["request_refusal_probe"]["passed"]:
        raise PreflightError("the neighbour-substitution refusal probe failed")
    if not substitution["active_exact_cell_probe"]["passed"]:
        raise PreflightError("the active exact-cell probe failed")
    if not ood_guard["passed"]:
        raise PreflightError("the OOD branch guard failed")
    for record in frontier_records:
        if not record["derived_window_matches_frozen_interval"]:
            raise PreflightError(
                f"frontier {record['path']} derived a window that misses the frozen interval"
            )
        if (record.get("sizing_source") or {}).get("nearest_price_substituted"):
            raise PreflightError(f"frontier {record['path']} substituted a neighbouring price")

    derivation = derive_issue367_preflight_passed(admission, walkthrough)

    document = {
        "schema": SCHEMA,
        "kind": KIND,
        "issue": ISSUE,
        "source_issue": SOURCE_ISSUE,
        "scenario_issue": SCENARIO_ISSUE,
        "scenario_id": SCENARIO_ID,
        "issue367_preflight_passed": derivation["issue367_preflight_passed"],
        "issue367_preflight_passed_derivation": derivation,
        "admission": admission,
        "ood_rule": rule,
        "provider": {
            "entry_point": (
                "tools/preflop/hybrid_response_runtime.py::resolve_hybrid_response"
            ),
            "provider_kind": runtime_metadata["provider_kind"],
            "decision_schema": runtime_metadata["decision_schema"],
            "contract_schema": runtime_metadata["contract_schema"],
            "route_sources": list(runtime_metadata["route_sources"]),
            "support_states": list(runtime_metadata["support_states"]),
            "action_space": list(runtime_metadata["action_space"]),
            "aggressive_actions": list(runtime_metadata["aggressive_actions"]),
            "rule": dict(runtime_metadata["rule"]),
            "spec": dict(runtime_metadata["spec"]),
            "ood_calibration": dict(runtime_metadata["ood_calibration"]),
            "generalized_calibration_report": dict(
                runtime_metadata["generalized_calibration_report"]
            ),
            "active_reference": dict(runtime_metadata["active_reference"]),
            "runtime": dict(runtime_metadata["runtime"]),
            "guarantees": dict(runtime_metadata["guarantees"]),
            "audit": dict(runtime_audit),
        },
        "scenario": {
            "issue": SCENARIO_ISSUE,
            "scenario_id": SCENARIO_ID,
            "root_path": list(ROOT_PATH),
            "initial_iso_target_total_bb": INITIAL_ISO_TARGET_TOTAL_BB,
            "required_node_count": REQUIRED_NODE_COUNT,
            "unresolved_sizing_frontier_count": UNRESOLVED_FRONTIER_COUNT,
            "fixture_sha256": sha256_file(FIXTURE_PATH),
            "required_tree_sha256": sha256_file(REQUIRED_TREE_PATH),
            "frontier_resolution_path": _relative(model.FRONTIER_RESOLUTION_PATH),
            "frontier_resolution_sha256": sha256_file(model.FRONTIER_RESOLUTION_PATH),
            "context_reconstruction_rule": (
                "public frozen fields only: the stack comes from the frozen #388 bucket "
                "representative (the in-bucket alternate is verified key-invariant), the actor's "
                "contribution is the public 'faced raise-to - to_call' and the faced raise-to is "
                "carried as faced_target_total_bb so it is never mistaken for a queried sizing"
            ),
        },
        "nodes_queried": len(nodes),
        "nodes": nodes,
        "sizing_frontiers_queried": len(frontier_records),
        "sizing_frontiers": frontier_records,
        "walkthrough": walkthrough,
        "nearest_lookup_audit": {
            **substitution,
            "faced_price_mapping_guard": mapping_guard,
            "nearest_price_substituted": False,
            "nearest_context_substituted": False,
            "runtime_declared_flags": {
                "metadata_guarantees": dict(runtime_metadata["guarantees"]),
                "runtime_audit": dict(runtime_audit),
            },
            "stack_bucket_reconstruction": {
                "buckets_seen": sorted(
                    {record["stack_reconstruction"]["bucket"] for record in nodes}
                ),
                "all_nodes_bucket_invariant": all(
                    record["stack_reconstruction"]["ood_feature_key_invariant"]
                    for record in nodes
                ),
                "not_a_neighbour_lookup": (
                    "the bucket is the frozen public stack identity of the node; the in-bucket "
                    "alternate yields the same OOD node labels, so no node is resolved against a "
                    "neighbouring observation"
                ),
            },
        },
        "boundary": {
            "issue367_executed": False,
            "hero_ev_executed": False,
            "recommendation_computed": False,
            "rollouts_executed": 0,
            "ev_values_computed": 0,
            "hero_ev_runner_imported": False,
            "test_consumed": False,
            "test_split_authorized": False,
            "validation_split_consumed": False,
            "admission_artifacts_read": [
                _relative(TERMINAL_REPORT_PATH),
                _relative(SPEC_PATH),
                _relative(MANIFEST_PATH),
                _relative(CALIBRATION_REPORT_PATH),
            ],
            "active_model_pointer_mutated": False,
            "protected_files_unchanged": True,
            "hand_history_files_opened": 0,
            "reads_stayed_inside_the_declared_frozen_evidence": True,
            "declared_evidence_paths": list(ALLOWED_EVIDENCE_PATHS),
            "nearest_price_substituted": False,
            "nearest_context_substituted": False,
            "hand_history_tripwire_rule": (
                "any open of a *.jsonl / *.zip / *.snapshots / *.snapshots.json file outside the "
                "declared frozen evidence, or of any file under training/datasets/, raises; the "
                "observed read set is additionally checked against the declared frozen evidence "
                "list"
            ),
        },
        "self_scans": {"holdout_scan": holdout_scan, "hero_ev_scan": hero_ev_scan},
        "evidence_bindings": {
            "preflight_tool_path": _relative(SOURCE_PATH),
            "preflight_tool_sha256": sha256_file(SOURCE_PATH),
            "runtime_module_path": _relative(RUNTIME_MODULE_PATH),
            "runtime_module_sha256": sha256_file(RUNTIME_MODULE_PATH),
            "router_module_path": _relative(ROUTER_MODULE_PATH),
            "router_module_sha256": sha256_file(ROUTER_MODULE_PATH),
            "spec_path": _relative(SPEC_PATH),
            "spec_byte_sha256": spec["byte_sha256"],
            "manifest_path": _relative(MANIFEST_PATH),
            "manifest_byte_sha256": manifest["byte_sha256"],
            "calibration_report_path": _relative(CALIBRATION_REPORT_PATH),
            "calibration_report_sha256": calibration["byte_sha256"],
            "terminal_report_path": _relative(TERMINAL_REPORT_PATH),
            "terminal_report_sha256": report["byte_sha256"],
            "ood_calibration_path": _relative(OOD_REPORT_PATH),
            "ood_calibration_sha256": sha256_file(OOD_REPORT_PATH),
            "required_tree_path": _relative(REQUIRED_TREE_PATH),
            "required_tree_sha256": sha256_file(REQUIRED_TREE_PATH),
            "fixture_path": _relative(FIXTURE_PATH),
            "fixture_sha256": sha256_file(FIXTURE_PATH),
            "frontier_resolution_path": _relative(model.FRONTIER_RESOLUTION_PATH),
            "frontier_resolution_sha256": sha256_file(model.FRONTIER_RESOLUTION_PATH),
            "dataset_contract_path": _relative(DATASET_CONTRACT_PATH),
            "dataset_contract_sha256": sha256_file(DATASET_CONTRACT_PATH),
        },
        "protected_files": protected_after,
        "observed_reads": observed_reads,
        "notes": [
            "The preflight walks the 38 required nodes of the scenario #321 response tree plus "
            "its 7 frozen raise-sizing frontiers and queries the #423 T7 hybrid runtime provider "
            "directly at each node's exact public context.",
            "Every visited decision is either DIRECT_EVAL (the router answered inside the "
            "calibrated domain with an analysis-admissible decision) or EXPLICIT_ABSTAIN (the "
            "frozen OOD gate abstained on a hard reason, or a channel refused fail-closed).",
            "The router's chosen source is recorded per decision; sparse in-domain branches are "
            "answered through the calibrated generalized channel exactly as the frozen route "
            "table requires, and a significant OOD branch stays blocking rather than being "
            "rescued by a neighbour.",
            "No nearest-price, nearest-context, representative-price, interpolated-price, "
            "legal-minimum or cross-context support substitution is applied; executable probes "
            "confirm a substitution request is refused with "
            "NEAREST_NEIGHBOUR_SUBSTITUTION_REFUSED and a perturbed request is recomputed.",
            "The walkthrough is recorded as evidence regardless of the admission outcome; when "
            "the terminal outcome does not admit the router the document states the blocking "
            "abstention, quotes the frozen outcome rule and reports no Hero EV and no #367 run.",
            "issue367_preflight_passed is derived mechanically from the terminal outcome and the "
            "frozen OOD rule: it is true only when the terminal outcome admits the router, the "
            "walkthrough is analysis-admissible and the structural preflight passed.",
            "TEST stays unconsumed and the VALIDATION split is never opened: only the published, "
            "content-addressed TRAIN-only terminal router report and the frozen calibration "
            "report are read as admission evidence, and no active model pointer is mutated.",
            "The marginal walkthrough queries no raise target, so each decision's sizing_source "
            "records the sizing channel the runtime declares for a raise at that exact context "
            "(conditioning target source and the engine's legal window verdict).",
        ],
    }
    summary = [
        f"#423 -> #367 preflight: {admission['outcome']}",
        f"terminal outcome: {admission['terminal_outcome']}",
        f"decisions visited: {walkthrough['decisions_visited']} "
        f"(direct-eval {walkthrough['direct_eval_decisions']}, "
        f"explicit abstain {walkthrough['explicit_abstain_decisions']})",
        f"sizing frontiers visited: {len(frontier_records)}",
        f"nearest-substitution probes passed: {substitution['probes_passed']}",
        f"issue367_preflight_passed: {derivation['issue367_preflight_passed']}",
    ]
    return document, summary


def persist(document: Mapping[str, Any]) -> dict[str, Any]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    data = serialize(document)
    digest = hashlib.sha256(data).hexdigest()
    (OUTPUT_DIR / NAME).write_bytes(data)
    payload_digest = canonical_sha256(document)
    (OUTPUT_DIR / SIDECAR_NAME).write_text(
        f"{digest}  {NAME}\n"
        f"# canonical_payload_sha256 {payload_digest}\n"
        f"# outcome {document['admission']['outcome']}\n"
        f"# terminal_outcome {document['admission']['terminal_outcome']}\n"
        f"# issue367_preflight_passed {str(document['issue367_preflight_passed']).lower()}\n",
        encoding="utf-8",
    )
    return {
        "path": _relative(OUTPUT_DIR / NAME),
        "sha256": digest,
        "canonical_payload_sha256": payload_digest,
        "sidecar": _relative(OUTPUT_DIR / SIDECAR_NAME),
    }


def check() -> int:
    document, _summary = build()
    expected = serialize(document)
    problems: list[str] = []
    path = OUTPUT_DIR / NAME
    if not path.is_file():
        problems.append(f"missing persisted preflight: {_relative(path)}")
    elif path.read_bytes() != expected:
        problems.append(f"{NAME} differs from a fresh preflight")
    sidecar = OUTPUT_DIR / SIDECAR_NAME
    if not sidecar.is_file():
        problems.append(f"missing sidecar: {_relative(sidecar)}")
    else:
        recorded = sidecar.read_text(encoding="utf-8").split()[0]
        if recorded != hashlib.sha256(expected).hexdigest():
            problems.append(f"{SIDECAR_NAME} does not pin the persisted preflight")
    if problems:
        for problem in problems:
            print(problem, file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "schema": SCHEMA,
                "check": "PASS",
                "path": _relative(path),
                "sha256": hashlib.sha256(expected).hexdigest(),
                "admission_outcome": document["admission"]["outcome"],
                "terminal_outcome": document["admission"]["terminal_outcome"],
                "issue367_preflight_passed": document["issue367_preflight_passed"],
                "nodes_queried": document["nodes_queried"],
                "sizing_frontiers_queried": document["sizing_frontiers_queried"],
                "direct_eval_decisions": document["walkthrough"]["direct_eval_decisions"],
                "explicit_abstain_decisions": document["walkthrough"][
                    "explicit_abstain_decisions"
                ],
            },
            indent=2,
        )
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the persisted preflight instead of rewriting it",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.check:
        return check()
    document, summary = build()
    index = persist(document)
    print(json.dumps(index, indent=2))
    for line in summary:
        print(line, file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""#421 -> #367 preflight: one direct model query per visited node, no EV.

This command walks the scenario #321 response tree -- the 38 required nodes of
the frozen #388 exact tree plus its 7 unresolved raise-sizing frontiers -- and
queries the #421 generalized adverse-response runtime provider
(``tools.preflop.generalized_response_runtime``) **directly at the exact public
context of each visited node**.  For every node it records the action
distribution, the frozen OOD status, the uncertainty bundle, the provenance and,
when a raise is simulated, the conditional sizing returned by the sizing model.

It is a *preflight*: it never runs the #367 Hero EV runner, never computes a
rollout, an EV or a recommendation, never consumes the TEST split and never
mutates an active model pointer.

Admission conditioning
----------------------

The frozen #421 protocol and candidate manifest both carry the #367 consumption
rule ``ISSUE367_CONSUMES_ONLY_AN_ADMITTED_CANDIDATE``: the candidate may only be
consumed by #367 once the one-shot VALIDATION evaluation returns
``ADMIT_CANDIDATE`` and every frozen gate passes.  The terminal decision
published beside the protocol is read here as *evidence*, never re-derived.

* ``ADMITTED`` -- every frozen gate passed and ``issue367_authorized`` is true;
  the walkthrough below is then the authoritative preflight evidence;
* ``ABSTAIN_BLOCKED_ADMISSION`` -- the frozen decision retains the active
  reference (or the candidate stays unresolved); the walkthrough is still
  executed and recorded, and the document states the blocking abstention and the
  frozen rule verbatim.  In that case #367 keeps its currently admitted model,
  no provider is wired for consumption and no Hero EV is computed.

Either way the walkthrough is fail-closed per node: a node is either
``DIRECT_EVAL`` (the model answered inside its calibrated domain) or
``EXPLICIT_ABSTAIN`` (the frozen OOD gate abstained, or the runtime refused with
a stable fail-closed code).  No third class exists, and no node is answered by a
neighbouring price, a neighbouring public context or a cross-context support
borrow -- every such substitution class is refused and the refusal is probed.

Reconstruction rule
-------------------

The frozen #388 tree stores the public stack as a bucket (``GT75_LE125``), not
as a number, while the response runtime needs ``effective_stack_bb``.  The
preflight therefore uses the *same* frozen bucket-representative convention the
#419 preflight uses (``STACK_BUCKET_REPRESENTATIVE``) and re-derives the
in-bucket alternate to prove the OOD node labels (and therefore the context
identity) are bucket-invariant.  Only public, frozen fields are consumed: the
actor's own pre-action contribution is the public ``faced raise-to - to_call``.

Reproduce: ``python3 tools/simulation/issue421_issue367_preflight.py``
Verify:    ``python3 tools/simulation/issue421_issue367_preflight.py --check``
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
from tools.preflop import generalized_response_runtime as runtime_provider  # noqa: E402
from tools.training.fit_model_a_preflop_sizing_hierarchical import (  # noqa: E402
    STACK_BUCKET_ALTERNATES,
    STACK_BUCKET_REPRESENTATIVE,
)

SCHEMA = "poker-issue421-issue367-preflight/v1"
KIND = "ISSUE367_PREFLIGHT"
ISSUE = 421
SOURCE_ISSUE = 367
SCENARIO_ISSUE = 321
SCENARIO_ID = "kts_sb_two_limp_iso4_three_calls_v1"
ROOT_PATH = ["SB:ISO@5"]
INITIAL_ISO_TARGET_TOTAL_BB = 5.0
REQUIRED_NODE_COUNT = 38
UNRESOLVED_FRONTIER_COUNT = 7

SOURCE_PATH = Path(__file__).resolve()
OUTPUT_DIR = ROOT / "analysis/issue421_generalized_response"
NAME = "ISSUE367_PREFLIGHT.json"
SIDECAR_NAME = "ISSUE367_PREFLIGHT.sha256"

REQUIRED_TREE_PATH = ROOT / "analysis/issue388_exact_tree/REQUIRED_EXACT_TREE.json"
FIXTURE_PATH = ROOT / "tests/fixtures/repro/kts_sb_two_limp_iso4_three_calls.snapshots.json"
PROTOCOL_PATH = OUTPUT_DIR / "FROZEN_VALIDATION_PROTOCOL.json"
PROTOCOL_SIDECAR = OUTPUT_DIR / "FROZEN_VALIDATION_PROTOCOL.sha256"
MANIFEST_PATH = OUTPUT_DIR / "CANDIDATE_MANIFEST.json"
MANIFEST_SIDECAR = OUTPUT_DIR / "CANDIDATE_MANIFEST.sha256"
DECISION_PATH = OUTPUT_DIR / "DECISION.json"
DECISION_SIDECAR = OUTPUT_DIR / "DECISION.sha256"
VALIDATION_RESULT_PATH = OUTPUT_DIR / "VALIDATION_RESULT.json"
VALIDATION_RESULT_SIDECAR = OUTPUT_DIR / "VALIDATION_RESULT.sha256"
OOD_REPORT_PATH = OUTPUT_DIR / "OOD_CALIBRATION_REPORT.json"
RUNTIME_MODULE_PATH = ROOT / "tools/preflop/generalized_response_runtime.py"
DATASET_CONTRACT_PATH = ROOT / "contracts/training/generalized-response-dataset.schema.json"

CANDIDATE_ID = "generalized-adverse-response-candidate-v1"
CANDIDATE_CANONICAL_SHA256 = (
    "c3f3573f3e80b3f7889dc8b1fd6f1948daeea95effc5a41a5d707385c4eed7dc"
)
CANDIDATE_BYTE_SHA256 = (
    "ea93e8c35e2604debd943495474cdb9262d724efb4a5caefe3723b53f23a59e7"
)
ISSUE367_RULE_ID = runtime_provider.ISSUE367_RULE_ID
ISSUE367_AUTHORIZING_OUTCOME = "ADMIT_CANDIDATE"

#: Active pointers and frozen evidence that must hash back unchanged after a run.
PROTECTED_FILES = (
    "training/models/preflop_population_model_v5.json",
    "training/models/postflop_population_model_v5.json",
    "training/registry.json",
    "training/populations/registry.json",
    "analysis/issue421_generalized_response/CANDIDATE_MANIFEST.json",
    "analysis/issue421_generalized_response/FROZEN_VALIDATION_PROTOCOL.json",
    "analysis/issue421_generalized_response/DECISION.json",
    "analysis/issue421_generalized_response/VALIDATION_RESULT.json",
    "analysis/issue388_exact_tree/REQUIRED_EXACT_TREE.json",
)

#: Substitutions that must never resolve a node on this surface.
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
#: the scenario, the candidate and the admission decision.  The build re-checks
#: the observed reads against this list, so nothing else can be pulled in.
ALLOWED_EVIDENCE_PATHS = (
    "analysis/issue388_exact_tree/REQUIRED_EXACT_TREE.json",
    "analysis/issue419_hierarchical_tree/raise_sizing_frontiers_v2/"
    "RAISE_SIZING_FRONTIER_RESOLUTION.json",
    "analysis/issue421_generalized_response/CANDIDATE_MANIFEST.json",
    "analysis/issue421_generalized_response/CANDIDATE_MANIFEST.sha256",
    "analysis/issue421_generalized_response/DECISION.json",
    "analysis/issue421_generalized_response/DECISION.sha256",
    "analysis/issue421_generalized_response/FROZEN_VALIDATION_PROTOCOL.json",
    "analysis/issue421_generalized_response/FROZEN_VALIDATION_PROTOCOL.sha256",
    "analysis/issue421_generalized_response/OOD_CALIBRATION_REPORT.json",
    "analysis/issue421_generalized_response/VALIDATION_RESULT.json",
    "analysis/issue421_generalized_response/VALIDATION_RESULT.sha256",
    "analysis/issue421_generalized_response/model/"
    "candidate_hierarchical_empirical_bayes_dirichlet.json",
    "analysis/issue421_generalized_response/model/"
    "candidate_regularized_multinomial_spline.json",
    "tests/fixtures/repro/kts_sb_two_limp_iso4_three_calls.snapshots.json",
    "contracts/training/generalized-response-dataset.schema.json",
    "tools/preflop/generalized_response_runtime.py",
    "tools/simulation/issue421_issue367_preflight.py",
)


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
            "validation/holdout module and opens no hand history; the published terminal "
            "decision and validation *result* are read as admission evidence, not as a split"
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


def load_frozen_protocol() -> dict[str, Any]:
    """The frozen #421 protocol that carries the #367 consumption rule."""
    digest = _verify_sidecar(PROTOCOL_PATH, PROTOCOL_SIDECAR)
    protocol = _load(PROTOCOL_PATH)
    if protocol.get("schema") != "poker-generalized-frozen-validation-protocol/v1":
        raise PreflightError("unexpected frozen protocol schema")
    if protocol.get("status") != "FROZEN_BEFORE_VALIDATION":
        raise PreflightError("the frozen protocol is not frozen before validation")
    rule = protocol.get("issue367_rule") or {}
    if rule.get("rule_id") != ISSUE367_RULE_ID:
        raise PreflightError("unexpected frozen #367 consumption rule id")
    if rule.get("authorized_at_freeze") is not False:
        raise PreflightError("#367 must stay unauthorized at freeze time")
    if rule.get("hero_ev_consumed") or rule.get("model_b_consumed"):
        raise PreflightError("the frozen rule must report no Hero EV and no Model B consumption")
    if rule.get("test_consumed") or rule.get("promotion_performed"):
        raise PreflightError("the frozen rule must report no TEST consumption and no promotion")
    for forbidden in ("NEAREST_PRICE", "NEAREST_CONTEXT", "HERO_EV", "MODEL_B", "TEST"):
        if forbidden not in (protocol.get("forbidden") or []):
            raise PreflightError(f"the frozen protocol must forbid {forbidden}")
    if CANDIDATE_CANONICAL_SHA256 not in json.dumps(rule.get("authorized_when")):
        raise PreflightError("the frozen #367 rule does not name this candidate identity")
    return {"document": protocol, "byte_sha256": digest}


def load_candidate_manifest(protocol: Mapping[str, Any]) -> dict[str, Any]:
    digest = _verify_sidecar(MANIFEST_PATH, MANIFEST_SIDECAR)
    manifest = _load(MANIFEST_PATH)
    if manifest.get("schema") != "poker-generalized-response-candidate-manifest/v1":
        raise PreflightError("unexpected candidate manifest schema")
    if manifest.get("status") != "FROZEN_BEFORE_VALIDATION":
        raise PreflightError("the candidate manifest is not frozen before validation")
    pinned = (protocol["document"].get("artifacts") or {}).get("candidate_manifest") or {}
    if pinned.get("sha256") != digest:
        raise PreflightError("the frozen protocol does not pin this candidate manifest")
    candidate = manifest.get("candidate") or {}
    if candidate.get("candidate_id") != CANDIDATE_ID:
        raise PreflightError("unexpected candidate id")
    if candidate.get("canonical_payload_sha256") != CANDIDATE_CANONICAL_SHA256:
        raise PreflightError("candidate canonical payload hash drifted from the frozen identity")
    if candidate.get("sha256") != CANDIDATE_BYTE_SHA256:
        raise PreflightError("candidate byte hash drifted from the frozen identity")
    if candidate.get("status") != "CANDIDATE_ONLY_NOT_ACTIVE":
        raise PreflightError("the candidate must stay candidate-only and inactive")
    if candidate.get("active_model_replaced") is not False:
        raise PreflightError("the candidate must not replace the active model")
    rule = manifest.get("issue367_consumption_rule") or {}
    if rule.get("rule_id") != ISSUE367_RULE_ID or rule.get("authorized_at_freeze") is not False:
        raise PreflightError("unexpected frozen #367 consumption rule in the manifest")
    if (manifest.get("ood_gate") or {}).get("calibration_report_sha256") != sha256_file(
        OOD_REPORT_PATH
    ):
        raise PreflightError("the OOD calibration report is not the one the manifest pins")
    return {"document": manifest, "byte_sha256": digest}


def load_terminal_decision(protocol: Mapping[str, Any]) -> dict[str, Any]:
    """The published, content-addressed terminal decision (admission evidence)."""
    digest = _verify_sidecar(DECISION_PATH, DECISION_SIDECAR)
    validation_digest = _verify_sidecar(VALIDATION_RESULT_PATH, VALIDATION_RESULT_SIDECAR)
    decision = _load(DECISION_PATH)
    validation = _load(VALIDATION_RESULT_PATH)
    if decision.get("schema") != "poker-generalized-response-terminal-decision/v1":
        raise PreflightError("unexpected terminal decision schema")
    if decision.get("terminal") is not True:
        raise PreflightError("the published decision is not terminal")
    if decision.get("issue") != ISSUE:
        raise PreflightError("the published decision belongs to another issue")
    if decision.get("validation_result_sha256") != validation_digest:
        raise PreflightError("the terminal decision does not pin this validation result")
    if validation.get("outcome") != decision.get("protocol_outcome"):
        raise PreflightError("the validation result outcome disagrees with the terminal decision")
    gate = next(
        (
            row
            for row in decision.get("gates") or []
            if row.get("id") == "protocol_frozen_before_validation"
        ),
        None,
    )
    if gate is None:
        raise PreflightError("the terminal decision lost its protocol-freeze gate")
    if (gate.get("observed") or {}).get("protocol_byte_sha256") != protocol["byte_sha256"]:
        raise PreflightError("the terminal decision was not decided against this frozen protocol")
    if decision.get("test_consumed") not in (False, None):
        raise PreflightError("the terminal decision must report TEST as unconsumed")
    if decision.get("test_authorized") not in (False, None):
        raise PreflightError("the terminal decision must report TEST as unauthorized")
    if decision.get("validation_consumed") is not True:
        raise PreflightError("the frozen decision must be the one-shot VALIDATION evaluation")
    return {
        "document": decision,
        "byte_sha256": digest,
        "validation_result": validation,
        "validation_result_sha256": validation_digest,
    }


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
    frontiers = model.load_raise_sizing_frontiers()
    if not frontiers.get("loaded"):
        raise PreflightError("the frozen raise-sizing frontier resolution is unavailable")
    if len(frontiers.get("frontiers") or []) != UNRESOLVED_FRONTIER_COUNT:
        raise PreflightError("the frozen frontier resolution must carry 7 frontiers")
    return frontiers


# ---------------------------------------------------------------------------
# admission conditioning
# ---------------------------------------------------------------------------


def issue367_admission(
    protocol: Mapping[str, Any],
    manifest: Mapping[str, Any],
    decision: Mapping[str, Any],
) -> dict[str, Any]:
    """Condition the preflight on the frozen #367 consumption rule."""
    frozen_rule = dict(protocol["document"]["issue367_rule"])
    manifest_rule = dict(manifest["document"]["issue367_consumption_rule"])
    for field in ("rule_id", "authorized_at_freeze", "authorized_when", "forbidden_while"):
        if frozen_rule.get(field) != manifest_rule.get(field):
            raise PreflightError(
                f"the frozen protocol and candidate manifest disagree on #367 rule field {field!r}"
            )
    validation = decision["validation_result"]
    outcome = str(validation.get("outcome") or "")
    declared = decision["document"].get("issue367_authorized")
    authorized = outcome == ISSUE367_AUTHORIZING_OUTCOME and declared is True
    if outcome != ISSUE367_AUTHORIZING_OUTCOME and declared is True:
        raise PreflightError("the decision authorizes #367 without a positive admission outcome")
    if authorized and decision["document"].get("failed_gates"):
        raise PreflightError("an admission cannot carry failed gates")

    blocking: list[str] = []
    if not authorized:
        blocking.append(f"VALIDATION outcome is {outcome or 'UNRESOLVED'}")
        blocking.extend(
            f"failed frozen gate: {gate}" for gate in decision["document"].get("failed_gates") or []
        )
        if outcome != ISSUE367_AUTHORIZING_OUTCOME:
            blocking.append("no ADMIT_CANDIDATE VALIDATION result exists for this candidate")
        else:
            blocking.append("the terminal decision does not authorize #367 consumption")
    return {
        "kind": "ISSUE367_ADMISSION_CONDITION",
        "rule_id": ISSUE367_RULE_ID,
        "question": frozen_rule.get("question"),
        "authorized": authorized,
        "authorized_when": list(frozen_rule.get("authorized_when") or []),
        "forbidden_while": list(frozen_rule.get("forbidden_while") or []),
        "consequence_when_forbidden": frozen_rule.get("consequence_when_forbidden"),
        "unchanged_by_this_freeze": frozen_rule.get("unchanged_by_this_freeze"),
        "consumption": "AUTHORIZED" if authorized else "FORBIDDEN",
        "outcome": "ADMITTED" if authorized else "ABSTAIN_BLOCKED_ADMISSION",
        "validation_outcome": outcome or None,
        "admission_decision": validation.get("decision"),
        "declared_issue367_authorized": declared,
        "failed_gates": list(decision["document"].get("failed_gates") or []),
        "passed_gates": list(decision["document"].get("passed_gates") or []),
        "criteria_passed": decision["document"].get("criteria_passed"),
        "criteria_total": decision["document"].get("criteria_total"),
        "blocking_reasons": blocking,
        "currently_admitted_model_a_for_367": dict(
            frozen_rule.get("currently_admitted_model_a_for_367") or {}
        ),
        "abstention": (
            None
            if authorized
            else {
                "code": "ISSUE367_ADMISSION_NOT_GRANTED",
                "detail": (
                    "the frozen candidate may not be consumed by #367: the preflight records "
                    "the direct-eval walkthrough as evidence only, wires no provider into #367 "
                    "and computes no Hero EV"
                ),
                "frozen_rule_id": ISSUE367_RULE_ID,
                "hero_ev_consumed": False,
                "model_b_consumed": False,
                "test_consumed": False,
                "active_model_pointer_mutation": False,
                "promotion_performed": False,
            }
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


def frontier_request_context(
    frontier: Mapping[str, Any], tree_nodes: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    """Public context of one frozen raise-sizing frontier.

    Each frozen frontier is the RAISE edge of one required tree node, so the
    full public context is that required node's frozen context plus the frozen
    engine interval.  The frozen interval is authoritative for the raise window
    (it is the engine's own ``min_raise_to``/``max_raise_to`` pair), so the cap
    never falls back to the bucket representative.
    """
    node_id = str(frontier.get("node_id"))
    node = tree_nodes.get(node_id)
    if node is None:
        raise PreflightError(f"frontier node {node_id} is not a required tree node")
    structural = dict(node["context"])
    frontier_context = dict(frontier.get("structural_context") or {})
    for field in ("family", "actor_position", "table_size", "raise_level"):
        if frontier_context.get(field) != structural.get(field):
            raise PreflightError(
                f"frontier {node_id} disagrees with its required node on {field!r}"
            )
    if sorted(frontier_context.get("live_positions") or []) != sorted(
        structural.get("live_positions") or []
    ):
        raise PreflightError(
            f"frontier {node_id} disagrees with its required node on the live position set"
        )
    if list(frontier_context.get("history") or []) != list(structural.get("history") or []):
        raise PreflightError(
            f"frontier {node_id} disagrees with its required node on the public history"
        )
    context = node_request_context(node)
    interval = frontier.get("legal_target_interval_bb")
    if not interval or len(interval) != 2:
        raise PreflightError(f"frontier {node_id} has no frozen legal target interval")
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
        "structural_live_positions": list(frontier_context.get("live_positions") or []),
        "required_node_live_positions": list(structural.get("live_positions") or []),
    }


# ---------------------------------------------------------------------------
# provider queries
# ---------------------------------------------------------------------------


#: Every documented fail-closed surface of the runtime provider.  A node whose
#: query trips one of these is recorded as an explicit abstention carrying the
#: stable code, never repaired with a neighbouring value.
FAIL_CLOSED_ERRORS = (
    runtime_provider.GeneralizedResponseRuntimeError,
    model.GeneralizedResponseModelError,
)


def _fail_closed_code(error: BaseException) -> str:
    code = getattr(error, "code", None)
    if code:
        return str(code)
    return type(error).__name__


def _compact_signals(signals: Mapping[str, Any]) -> dict[str, Any]:
    """The OOD signal bundle without the fields the uncertainty block repeats."""
    return {
        "feature_levels": dict(signals.get("feature_levels") or {}),
        "unseen_categories": dict(signals.get("unseen_categories") or {}),
        "axes": {axis: dict(entry) for axis, entry in (signals.get("axes") or {}).items()},
        "domain_distance": signals.get("domain_distance"),
        "local_support": dict(signals.get("local_support") or {}),
        "exact_context": dict(signals.get("exact_context") or {}),
    }


def _distribution(document: Mapping[str, Any]) -> dict[str, Any]:
    probabilities = {
        action: float(document["action_probabilities"][action]) for action in model.ACTIONS
    }
    return {
        "probabilities": probabilities,
        "probability_sum": document["probability_sum"],
        "normalization": document["normalization"],
        "illegal_mass": document["illegal_mass"],
        "selected_action": document["selected_action"],
        "selected_action_probability": document["uncertainty"]["selected_action_probability"],
    }


def _sizing_view(sizing: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if sizing is None:
        return None
    return {
        "schema": sizing["schema"],
        "action": sizing["action"],
        "status": sizing["status"],
        "fail_closed_reason": sizing["fail_closed_reason"],
        "legal_window": dict(sizing["legal_window"] or {}),
        "support": dict(sizing["support"] or {}),
        "uncertainty": (
            None if sizing["uncertainty"] is None else dict(sizing["uncertainty"])
        ),
        "quantiles_bb": dict(sizing["quantiles_bb"] or {}),
        "generated_sizings_bb": list(sizing["generated_sizings_bb"]),
        "generated_count": sizing["generated_count"],
        "illegal_count": sizing["illegal_count"],
        "nearest_price_substituted": sizing["nearest_price_substituted"],
        "nearest_context_substituted": sizing["nearest_context_substituted"],
    }


def _model_view(document: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "status": document["status"],
        "usable": document["usable"],
        "abstain": document["abstain"],
        "fail_closed": document["fail_closed"],
        "fail_closed_reason": document["fail_closed_reason"],
        "context_key": document["context_key"],
        "legal_actions": list(document["legal_actions"]),
        "masked_actions": list(document["masked_actions"]),
        "action_distribution": _distribution(document),
        "ood_status": {
            "status": document["ood"]["status"],
            "supported": document["ood"]["supported"],
            "abstain": document["ood"]["abstain"],
            "high_uncertainty": document["ood"]["high_uncertainty"],
            "decided_by": document["ood"]["decided_by"],
            "status_definition": document["ood"]["status_definition"],
            "reasons": list(document["ood"]["reasons"]),
            "hard_reasons": list(document["ood"]["hard_reasons"]),
            "soft_reasons": list(document["ood"]["soft_reasons"]),
            "signals": _compact_signals(document["ood"]["signals"]),
            "validation_consumed": document["ood"]["validation_consumed"],
            "test_consumed": document["ood"]["test_consumed"],
        },
        "uncertainty": dict(document["uncertainty"]),
        "request": dict(document["request"]),
        "provenance": {
            "runtime": dict(document["provenance"]["runtime"]),
            "candidate": dict(document["provenance"]["candidate"]),
            "ood_calibration": dict(document["provenance"]["ood_calibration"]),
            "frozen_validation_result": dict(document["provenance"]["frozen_validation_result"]),
            "issue367": dict(document["provenance"]["issue367"]),
            "context": dict(document["provenance"]["context"]),
            "identity_flags": dict(document["provenance"]["identity_flags"]),
        },
        "selected_sizing_bb": document["selected_sizing_bb"],
        "decision_canonical_sha256": document["decision_canonical_sha256"],
    }


def _base_query(
    runtime: runtime_provider.GeneralizedResponseRuntime,
    context: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """One direct query, classified as direct-eval or explicit abstention."""
    try:
        document = runtime.resolve(context, include_sizing=True)
    except FAIL_CLOSED_ERRORS as error:
        return None, {"code": _fail_closed_code(error), "message": str(error)}
    return document, None


def _raise_simulation(
    runtime: runtime_provider.GeneralizedResponseRuntime,
    context: Mapping[str, Any],
    legal_actions: Sequence[str],
    structural_actions: Sequence[str],
) -> dict[str, Any]:
    """Simulate the node's raise and record the conditional sizing (or refusal)."""
    raise_exposed = "RAISE" in set(structural_actions)
    if "RAISE" not in legal_actions:
        return {
            "state": "NO_RAISE_ACTION",
            "reason": "RAISE_NOT_IN_THE_DERIVED_LEGAL_SPACE",
            "requested_action": None,
            "structural_raise_exposed": raise_exposed,
            "sizing": None,
            "selected_sizing_bb": None,
        }
    try:
        document = runtime.resolve(context, action="RAISE", include_sizing=True)
    except FAIL_CLOSED_ERRORS as error:
        return {
            "state": "RAISE_SIMULATION_FAIL_CLOSED",
            "reason": _fail_closed_code(error),
            "requested_action": "RAISE",
            "structural_raise_exposed": raise_exposed,
            "sizing": None,
            "selected_sizing_bb": None,
        }
    sizing = document["sizing"]
    resolved = bool(sizing and sizing["status"] == "RESOLVED")
    return {
        "state": "RAISE_SIZING_RESOLVED" if resolved else "RAISE_SIZING_FAIL_CLOSED",
        "reason": None if resolved else (sizing or {}).get("fail_closed_reason"),
        "requested_action": "RAISE",
        "structural_raise_exposed": raise_exposed,
        "sizing": _sizing_view(sizing),
        "selected_sizing_bb": document["selected_sizing_bb"],
        "decision_canonical_sha256": document["decision_canonical_sha256"],
    }


def node_record(
    index: int,
    node: Mapping[str, Any],
    runtime: runtime_provider.GeneralizedResponseRuntime,
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
        record.update(
            {
                "decision_class": "EXPLICIT_ABSTAIN",
                "abstention": {
                    "code": (abstention or {}).get("code"),
                    "message": (abstention or {}).get("message"),
                    "selected_action": None,
                    "sizing": None,
                },
                "model": None,
                "raise_simulation": {
                    "state": "NOT_SIMULATED_BASE_QUERY_ABSTAINED",
                    "reason": (abstention or {}).get("code"),
                    "requested_action": None,
                    "structural_raise_exposed": "RAISE" in set(structural_actions),
                    "sizing": None,
                    "selected_sizing_bb": None,
                },
            }
        )
        return record

    view = _model_view(document)
    record.update(
        {
            "decision_class": "DIRECT_EVAL" if document["usable"] else "EXPLICIT_ABSTAIN",
            "abstention": (
                None
                if document["usable"]
                else {
                    "code": document["fail_closed_reason"],
                    "message": "the frozen OOD gate abstained for this context",
                    "hard_reasons": view["ood_status"]["hard_reasons"],
                    "selected_action": None,
                    "sizing": None,
                }
            ),
            "model": view,
            "raise_simulation": _raise_simulation(
                runtime, context, view["legal_actions"], structural_actions
            ),
        }
    )
    return record


def frontier_record(
    index: int,
    frontier: Mapping[str, Any],
    node: Mapping[str, Any],
    runtime: runtime_provider.GeneralizedResponseRuntime,
) -> dict[str, Any]:
    context = frontier_request_context(frontier, {str(node["id"]): node})
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
        "exact_tree_status": "UNRESOLVED",
        "exact_tree_satisfied": False,
        "independent_of_the_response_model": bool(
            frontier.get("independent_of_the_response_model")
        ),
    }
    if document is None:
        record.update(
            {
                "decision_class": "EXPLICIT_ABSTAIN",
                "abstention": {
                    "code": (abstention or {}).get("code"),
                    "message": (abstention or {}).get("message"),
                    "selected_action": None,
                    "sizing": None,
                },
                "model": None,
                "raise_simulation": {
                    "state": "NOT_SIMULATED_BASE_QUERY_ABSTAINED",
                    "reason": (abstention or {}).get("code"),
                    "sizing": None,
                    "selected_sizing_bb": None,
                },
                "derived_window_bb": None,
                "derived_window_matches_frozen_interval": False,
            }
        )
        return record

    view = _model_view(document)
    simulation = _raise_simulation(runtime, context, view["legal_actions"], ("RAISE",))
    sizing = simulation["sizing"] or {}
    window = sizing.get("legal_window") or {}
    floor = window.get("floor_bb")
    cap = window.get("cap_bb")
    matches = bool(
        simulation["state"] == "RAISE_SIZING_RESOLVED"
        and floor is not None
        and cap is not None
        and math.isclose(float(floor), interval[0], abs_tol=1e-6)
        and math.isclose(float(cap), interval[1], abs_tol=1e-6)
    )
    record.update(
        {
            "decision_class": "DIRECT_EVAL" if document["usable"] else "EXPLICIT_ABSTAIN",
            "abstention": (
                None
                if document["usable"]
                else {
                    "code": document["fail_closed_reason"],
                    "message": "the frozen OOD gate abstained for this context",
                    "hard_reasons": view["ood_status"]["hard_reasons"],
                    "selected_action": None,
                    "sizing": None,
                }
            ),
            "model": view,
            "raise_simulation": simulation,
            "derived_window_bb": [floor, cap],
            "derived_window_matches_frozen_interval": matches,
            "window_bounds_source": window.get("bounds_source"),
        }
    )
    return record


# ---------------------------------------------------------------------------
# audits
# ---------------------------------------------------------------------------


def nearest_substitution_probes(
    runtime: runtime_provider.GeneralizedResponseRuntime,
    root_node: Mapping[str, Any],
    frontier: Mapping[str, Any],
    frontier_node: Mapping[str, Any],
) -> dict[str, Any]:
    """Executable probes that a changed request is recomputed, never snapped."""
    base = node_request_context(root_node)
    exact = runtime.resolve(base, include_sizing=False)

    shifted = dict(base)
    shifted["to_call_bb"] = float(base["to_call_bb"]) + 0.2
    shifted_document = runtime.resolve(shifted, include_sizing=False)
    price_probe = {
        "probe": "PRICE_RECOMPUTATION",
        "requested": {"to_call_bb": base["to_call_bb"]},
        "perturbed": {"to_call_bb": shifted["to_call_bb"]},
        "requested_distribution": dict(exact["action_probabilities"]),
        "perturbed_distribution": dict(shifted_document["action_probabilities"]),
        "decision_changed": (
            exact["decision_canonical_sha256"] != shifted_document["decision_canonical_sha256"]
        ),
        "evaluation": exact["request"]["evaluation"],
        "interpolation": exact["request"]["interpolation"],
    }
    price_probe["passed"] = bool(
        price_probe["decision_changed"]
        and price_probe["evaluation"] == "direct_recomputation"
        and price_probe["interpolation"] == "linear_spline_partition_of_unity"
    )

    other = dict(base)
    other["family"] = "LIMPER_VS_ISO" if base["family"] != "LIMPER_VS_ISO" else "VS_ISO"
    other["aggressor_position"] = "SB"
    other_document = runtime.resolve(other, include_sizing=False)
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

    frontier_context = frontier_request_context(frontier, {str(frontier_node["id"]): frontier_node})
    wide = runtime.resolve(frontier_context, action="RAISE", include_sizing=True)
    narrowed_context = dict(frontier_context)
    narrowed_context["legal_target_interval_bb"] = [
        float(frontier_context["legal_target_interval_bb"][0]),
        float(frontier_context["legal_target_interval_bb"][1]) - 10.0,
    ]
    narrowed = runtime.resolve(narrowed_context, action="RAISE", include_sizing=True)
    sizing_probe = {
        "probe": "SIZING_WINDOW_RECOMPUTATION",
        "requested_interval_bb": list(frontier_context["legal_target_interval_bb"]),
        "narrowed_interval_bb": list(narrowed_context["legal_target_interval_bb"]),
        "requested_window_bb": [
            (wide["sizing"] or {}).get("legal_window", {}).get("floor_bb"),
            (wide["sizing"] or {}).get("legal_window", {}).get("cap_bb"),
        ],
        "narrowed_window_bb": [
            (narrowed["sizing"] or {}).get("legal_window", {}).get("floor_bb"),
            (narrowed["sizing"] or {}).get("legal_window", {}).get("cap_bb"),
        ],
        "window_changed": (
            (wide["sizing"] or {}).get("legal_window")
            != (narrowed["sizing"] or {}).get("legal_window")
        ),
        "decision_changed": (
            wide["decision_canonical_sha256"] != narrowed["decision_canonical_sha256"]
        ),
    }
    sizing_probe["passed"] = bool(
        sizing_probe["window_changed"] and sizing_probe["decision_changed"]
    )

    probes = [price_probe, context_probe, sizing_probe]
    return {
        "rule": "A_CHANGED_REQUEST_IS_RECOMPUTED_NEVER_SNAPPED_TO_A_NEIGHBOUR",
        "substitution_classes_refused": list(SUBSTITUTION_CLASSES),
        "probes": probes,
        "probes_passed": all(probe["passed"] for probe in probes),
    }


def ood_abstention_probe(
    runtime: runtime_provider.GeneralizedResponseRuntime,
) -> dict[str, Any]:
    """Prove the abstention wiring is real: an unseen category must abstain."""
    probe = {
        "family": "OPEN_SHOVE_PREFLIGHT_PROBE",
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
        "preflight_probe": True,
    }
    document = runtime.resolve(probe, include_sizing=True)
    return {
        "probe": "OOD_ABSTENTION_WIRING",
        "status": document["status"],
        "abstain": document["abstain"],
        "selected_action": document["selected_action"],
        "selected_sizing_bb": document["selected_sizing_bb"],
        "hard_reasons": list(document["ood"]["hard_reasons"]),
        "passed": bool(
            document["status"] == runtime_provider.STATUS_ABSTAIN
            and document["abstain"]
            and document["selected_action"] is None
            and document["selected_sizing_bb"] is None
            and "UNSEEN_CATEGORY" in document["ood"]["hard_reasons"]
        ),
    }


def faced_price_mapping_guard(
    runtime: runtime_provider.GeneralizedResponseRuntime,
    nodes: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Show why the faced raise-to is never passed as a queried sizing.

    The frozen #388 tree stores, in ``target_total_bb``, the raise-to the actor
    *faces*, while the frozen #421 dataset contract defines that same field as
    the actor's own RAISE/JAM total contribution (null for FOLD/CALL).  Passing
    the faced price as a queried sizing therefore asks the sizing axis about a
    price the actor never chose; the guard records what that misreading would do
    so the mapping stays auditable instead of silent.

    Two refusals are recorded, and both are declared by the runtime: the frozen
    OOD gate abstains when the misread target also leaves the calibrated domain
    (``EXTRAPOLATION_SIZING``), and the legal-window declaration fails closed
    with ``ILLEGAL_SIZING_GENERATED`` when the context is otherwise answerable
    but the misread target is not a legal raise target of that actor.
    """
    abstaining: list[dict[str, Any]] = []
    refusal_codes: dict[str, int] = {}
    for node in nodes:
        context = node_request_context(node)
        context["target_total_bb"] = context["faced_target_total_bb"]
        document, error = _base_query(runtime, context)
        if document is not None and document["usable"]:
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
                    [] if document is None else list(document["ood"]["hard_reasons"])
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
        "misreading_is_not_used": True,
    }


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------


def build() -> tuple[dict[str, Any], list[str]]:
    holdout_scan = verify_no_holdout_access()
    hero_ev_scan = verify_no_hero_ev_execution()
    protected_before = protected_hashes()
    hero_ev_modules_before = set(hero_ev_modules_present())

    with hand_history_tripwire() as opened:
        protocol = load_frozen_protocol()
        manifest = load_candidate_manifest(protocol)
        decision = load_terminal_decision(protocol)
        tree = load_required_tree()
        frontiers = load_frontiers()
        runtime = runtime_provider.load_runtime(CANDIDATE_ID, CANDIDATE_CANONICAL_SHA256)
        admission = issue367_admission(protocol, manifest, decision)

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
        nearest = nearest_substitution_probes(
            runtime,
            root_node,
            first_frontier,
            tree_nodes[str(first_frontier["node_id"])],
        )
        abstention_probe = ood_abstention_probe(runtime)
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

    classes = [record["decision_class"] for record in nodes]
    direct_eval = classes.count("DIRECT_EVAL")
    explicit_abstain = classes.count("EXPLICIT_ABSTAIN")
    if direct_eval + explicit_abstain != len(nodes):
        raise PreflightError("a visited node was neither direct-evaluated nor abstained")
    raise_states: dict[str, int] = {}
    raise_failures: dict[str, int] = {}
    for record in nodes:
        simulation = record["raise_simulation"]
        state = simulation["state"]
        raise_states[state] = raise_states.get(state, 0) + 1
        if state == "RAISE_SIZING_FAIL_CLOSED" and simulation.get("reason"):
            raise_failures[simulation["reason"]] = raise_failures.get(simulation["reason"], 0) + 1
    raise_attempts = (
        raise_states.get("RAISE_SIZING_RESOLVED", 0) + raise_states.get("RAISE_SIZING_FAIL_CLOSED", 0)
    )
    if not nearest["probes_passed"]:
        raise PreflightError("a nearest-substitution probe failed")
    if not abstention_probe["passed"]:
        raise PreflightError("the OOD abstention wiring probe failed")
    for record in frontier_records:
        simulation = record["raise_simulation"]
        if simulation["state"] != "RAISE_SIZING_RESOLVED":
            raise PreflightError(
                f"frontier {record['path']} did not resolve a conditional raise sizing"
            )
        if not record["derived_window_matches_frozen_interval"]:
            raise PreflightError(
                f"frontier {record['path']} derived a window that misses the frozen interval"
            )
        if (simulation["sizing"] or {}).get("illegal_count"):
            raise PreflightError(f"frontier {record['path']} generated an illegal sizing")

    document = {
        "schema": SCHEMA,
        "kind": KIND,
        "issue": ISSUE,
        "source_issue": SOURCE_ISSUE,
        "scenario_issue": SCENARIO_ISSUE,
        "scenario_id": SCENARIO_ID,
        "admission": admission,
        "provider": {
            "entry_point": (
                "tools/preflop/generalized_response_runtime.py::resolve_generalized_response"
            ),
            "provider_kind": runtime_metadata["provider_kind"],
            "research_status": runtime_metadata["research_status"],
            "candidate_id": runtime_metadata["identity"]["candidate_id"],
            "architecture": runtime_metadata["identity"]["architecture"],
            "candidate_canonical_payload_sha256": runtime_metadata["identity"][
                "canonical_payload_sha256"
            ],
            "candidate_artifact_sha256": runtime_metadata["identity"]["artifact_sha256"],
            "deterministic_seed": runtime_metadata["identity"]["seed"],
            "action_space": list(runtime_metadata["action_space"]),
            "statuses": list(runtime_metadata["statuses"]),
            "ood_gate": dict(runtime_metadata["ood_gate"]),
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
        "direct_evaluation_audit": {
            "rule": "EVERY_VISITED_NODE_IS_DIRECT_EVAL_OR_EXPLICIT_ABSTAIN",
            "nodes_visited": len(nodes),
            "direct_eval_nodes": direct_eval,
            "explicit_abstain_nodes": explicit_abstain,
            "every_visited_node_classified": True,
            "raise_simulation_states": dict(sorted(raise_states.items())),
            "raise_simulations_attempted": raise_attempts,
            "raise_sizing_fail_closed_reasons": dict(sorted(raise_failures.items())),
            "raise_sizing_abstentions_are_explicit": True,
            "frontiers_visited": len(frontier_records),
            "frontier_raise_sizing_resolved": sum(
                1
                for record in frontier_records
                if record["raise_simulation"]["state"] == "RAISE_SIZING_RESOLVED"
            ),
            "frontiers_matching_the_frozen_interval": sum(
                1
                for record in frontier_records
                if record["derived_window_matches_frozen_interval"]
            ),
            "ood_abstention_probe": abstention_probe,
        },
        "nearest_lookup_audit": {
            **nearest,
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
                _relative(DECISION_PATH),
                _relative(VALIDATION_RESULT_PATH),
                _relative(PROTOCOL_PATH),
                _relative(MANIFEST_PATH),
            ],
            "active_model_pointer_mutated": False,
            "protected_files_unchanged": True,
            "hand_history_files_opened": 0,
            "reads_stayed_inside_the_declared_frozen_evidence": True,
            "declared_evidence_paths": list(ALLOWED_EVIDENCE_PATHS),
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
            "protocol_path": _relative(PROTOCOL_PATH),
            "protocol_byte_sha256": protocol["byte_sha256"],
            "candidate_manifest_path": _relative(MANIFEST_PATH),
            "candidate_manifest_sha256": manifest["byte_sha256"],
            "candidate_canonical_payload_sha256": CANDIDATE_CANONICAL_SHA256,
            "candidate_byte_sha256": CANDIDATE_BYTE_SHA256,
            "ood_calibration_path": _relative(OOD_REPORT_PATH),
            "ood_calibration_sha256": sha256_file(OOD_REPORT_PATH),
            "decision_path": _relative(DECISION_PATH),
            "decision_sha256": decision["byte_sha256"],
            "validation_result_path": _relative(VALIDATION_RESULT_PATH),
            "validation_result_sha256": decision["validation_result_sha256"],
            "required_tree_path": _relative(REQUIRED_TREE_PATH),
            "required_tree_sha256": sha256_file(REQUIRED_TREE_PATH),
            "fixture_path": _relative(FIXTURE_PATH),
            "fixture_sha256": sha256_file(FIXTURE_PATH),
            "frontier_resolution_sha256": sha256_file(model.FRONTIER_RESOLUTION_PATH),
            "dataset_contract_path": _relative(DATASET_CONTRACT_PATH),
            "dataset_contract_sha256": sha256_file(DATASET_CONTRACT_PATH),
        },
        "protected_files": protected_after,
        "notes": [
            "The preflight walks the 38 required nodes of the scenario #321 response tree plus "
            "its 7 frozen raise-sizing frontiers and queries the #421 runtime provider directly "
            "at each node's exact public context.",
            "Every visited node is either DIRECT_EVAL (answered inside the calibrated domain) or "
            "EXPLICIT_ABSTAIN (the frozen OOD gate abstained or the runtime refused fail-closed).",
            "No nearest-price, nearest-context, representative-price, interpolated-price, "
            "legal-minimum or cross-context support substitution is applied; executable probes "
            "confirm a changed request is recomputed instead of snapped to a neighbour.",
            "Each node's action distribution is the *marginal* response distribution at the exact "
            "queried public context: no raise target is queried for it, so the model applies its "
            "own documented default pot-relative raise size (the request echo carries "
            "sizing_source='default_pot_relative').  The frozen #388 'target_total_bb' is the "
            "raise-to the actor *faces* and is recorded as faced_target_total_bb; passing it as a "
            "queried sizing would query the sizing axis at the faced price instead of the actor's "
            "own raise target.",
            "A node whose raise window is empty below the effective stack (a re-raise facing an "
            "all-in) is not repaired: the conditional sizing fails closed with a reason code and "
            "the node is recorded as an explicit sizing abstention.",
            "No Hero EV, no rollout, no recommendation and no #367 execution: the #367 runner is "
            "neither imported nor executed and this preflight never wires a provider for "
            "consumption.",
            "TEST stays unconsumed and the VALIDATION split is never re-opened: only the "
            "published, content-addressed terminal decision and validation *result* are read as "
            "admission evidence, and no active model pointer is mutated.",
            "The direct-eval walkthrough is recorded as evidence regardless of the admission "
            "outcome; when the frozen rule forbids consumption the document states the blocking "
            "abstention and quotes the frozen rule verbatim.",
        ],
    }
    summary = [
        f"#421 -> #367 preflight: {admission['outcome']}",
        f"nodes visited: {len(nodes)} (direct-eval {direct_eval}, explicit abstain {explicit_abstain})",
        f"raise-sizing frontiers visited: {len(frontier_records)}",
        f"nearest-substitution probes passed: {nearest['probes_passed']}",
        f"#367 consumption: {admission['consumption']}",
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
        f"# outcome {document['admission']['outcome']}\n",
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
                "nodes_queried": document["nodes_queried"],
                "sizing_frontiers_queried": document["sizing_frontiers_queried"],
                "direct_eval_nodes": document["direct_evaluation_audit"]["direct_eval_nodes"],
                "explicit_abstain_nodes": document["direct_evaluation_audit"][
                    "explicit_abstain_nodes"
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

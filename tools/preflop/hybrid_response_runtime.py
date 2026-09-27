#!/usr/bin/env python3
"""#423 T7 runtime provider: hybrid preflop response decision with provenance.

This module is the *runtime* counterpart of the frozen #423 hybrid router
(:mod:`tools.preflop.hybrid_response_router`).  It turns one public preflop
request into a single, machine-readable decision document whose every field is
declared by the frozen runtime contract of
``analysis/issue423_hybrid_router/HYBRID_ROUTER_SPEC.json``
(``poker-hybrid-router-runtime-contract/v1``): ``route_source``,
``model_id``/``model_hash``, ``support_state``, ``uncertainty``, ``ood_status``,
``probabilities``, the sizing provenance of an aggressive answer,
``analysis_admissible`` and the reason codes of the decision.

What the provider consumes
--------------------------

* the **frozen spec** ``HYBRID_ROUTER_SPEC.json``, pinned by both its byte
  digest and the frozen ``ROUTER_MANIFEST.json`` entry.  The provider refuses to
  answer when the spec drifted: the route sources, the runtime contract, the
  split policy and the reason-code catalog it declares are read, not guessed.
* the **calibrated generalized channel**: the frozen #423 T2 calibration report
  (``GENERALIZED_CALIBRATION_REPORT.json``, digest-pinned) names the retained
  architecture/method of the sparse channel, and the frozen #421 generalized
  runtime (``tools/preflop/generalized_response_runtime.py``) supplies its
  probabilities and its conditional raise sizing.
* the **active Model A reference** (``training/models/preflop_population_model_v5.json``,
  digest-pinned): the ``ACTIVE_STRONG_SUPPORT`` branch is answered only by an
  **exact-cell lookup** of the active population model, mirroring the engine's
  own ``exactStruct`` predicate over the request's ``table_size``,
  ``raise_level``, ``family``, ``live_positions``, ``all_in_positions`` and
  ``history``.  A request that does not carry those identity fields has no
  exact active cell and abstains; the nearest active node is never read.

No nearest substitution, ever
-----------------------------

The router never substitutes a neighbouring context for the queried one and
never substitutes a neighbouring price for the queried sizing target; this
provider inherits that refusal and extends it to the active reference: when the
router routes to ``ACTIVE_STRONG_SUPPORT`` but the active model carries **no
exact cell** for the request, the provider abstains fail-closed
(``ACTIVE_EXACT_CELL_UNAVAILABLE``) instead of reading the nearest active node.
An explicit caller request for a substitution
(``allow_nearest_price`` / ``allow_nearest_context`` /
``allow_nearest_neighbour`` / a ``nearest_*_substituted=True`` flag) is refused
with the stable code ``NEAREST_NEIGHBOUR_SUBSTITUTION_REFUSED`` before any
decision is computed.

Fail-closed abstention
----------------------

An out-of-domain context abstains through the frozen #421 gate: the document
carries ``route_source="OOD_ABSTAIN"``, no probabilities, no selected action and
no sizing, and ``analysis_admissible=false``.  A channel-level refusal on an
otherwise answerable route (the active exact cell is absent, the calibrated
channel abstained, or the queried raise target leaves the engine's legal window)
downgrades the emitted decision to the same abstention surface and records the
machine-readable ``fail_closed_reason`` and the applied runtime reason codes;
``resolve(..., strict=True)`` re-raises the underlying refusal instead.

Byte-stable determinism
-----------------------

Every float of the document is quantised on the canonical decimal grid of
:mod:`tools.preflop.generalized_response_runtime` (``canonical_float`` /
``canonical_floats``) and every embedded legal distribution is re-closed with
its ``canonical_legal_distribution`` (``math.fsum``, illegal mass exactly
``0.0``), so the same context always produces the same bytes and the emitted
``probability_sum`` is exactly ``1.0``.  The document is serialised by
``canonical_json`` (sorted keys, ASCII, compact separators) and self-digested
with the runtime's ``decision_canonical_sha256``.

A split outside the frozen policy is refused before a decision is computed: a
``TEST`` row raises ``TEST_SPLIT_NOT_CONSUMABLE`` and a ``VALIDATION`` row
raises ``REFUSED_SPLIT`` (the frozen ``split_policy`` refuses both).

Only the Python standard library and repository modules are used.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.preflop import generalized_response_model as model  # noqa: E402
from tools.preflop import generalized_response_runtime as runtime  # noqa: E402
from tools.preflop import hybrid_response_router as router  # noqa: E402
from tools.training.evaluate_preflop_topology_candidate import (  # noqa: E402
    by_actor,
    runtime_exact,
)
from tools.training.preflop_policy169 import decode_policy169, hand_weights  # noqa: E402

MODULE_PATH = Path(__file__).resolve()

#: The decision document this provider emits, and the contract it satisfies.
HYBRID_RUNTIME_DECISION_SCHEMA = "poker-hybrid-response-runtime-decision/v1"
HYBRID_RUNTIME_PROVIDER_SCHEMA = "poker-hybrid-response-runtime-provider/v1"
SIZING_PROVENANCE_SCHEMA = "poker-hybrid-response-sizing-provenance/v1"
CONTRACT_SCHEMA = router.ROUTING_CONTRACT_SCHEMA

#: The frozen artifacts the provider consumes, with their pinned digests.
SPEC_PATH = ROOT / "analysis/issue423_hybrid_router/HYBRID_ROUTER_SPEC.json"
SPEC_SHA256 = "15c14c4ad0acddc65e240673cf8d148e2cd40dfb3d6fc43170ab8c2bb814d075"
SPEC_SCHEMA = "poker-hybrid-router-spec/v1"
MANIFEST_PATH = ROOT / "analysis/issue423_hybrid_router/ROUTER_MANIFEST.json"
MANIFEST_SHA256 = "c7c63cc89f76184d974b9764358311b0dc115e9167e8ab230e84e6389381fd99"
MANIFEST_SCHEMA = "poker-hybrid-router-criteria-manifest/v1"
CALIBRATION_REPORT_PATH = (
    ROOT / "analysis/issue423_hybrid_router/GENERALIZED_CALIBRATION_REPORT.json"
)
CALIBRATION_REPORT_SHA256 = (
    "a79d89c21610d42f4f083c43d3b7f1f9dfaf6ea5e104be558b3b06704f3be5cd"
)
CALIBRATION_REPORT_SCHEMA = "poker-generalized-response-calibration-report/v1"
ACTIVE_MODEL_PATH = ROOT / "training/models/preflop_population_model_v5.json"
ACTIVE_MODEL_SHA256 = "ff952055ca4ee051a3ac9607d513fdecac0a320a31f658ecfd8a11d8448975ca"

#: Model identities declared by the frozen spec / manifest.
ACTIVE_MODEL_ID = "active_model_a_preflop_population"
GENERALIZED_MODEL_ID = "generalized_adverse_response_candidate_v1"
NO_MODEL_ID = "none"

#: The sizing channel shared by both branches (see the module docstring).
SIZING_CHANNEL_ID = "calibrated_generalized_raise_sizing"
SIZING_MODULE_PATH = "tools/preflop/generalized_response_model.py"

#: Stable channel names of the two probability providers.
ACTIVE_CHANNEL_NAME = "ACTIVE_MODEL_A_EXACT_CELL"
CALIBRATED_CHANNEL_NAME = "CALIBRATED_GENERALIZED_CHANNEL"
DEFAULT_CHANNEL_NAME: dict[str, str] = {
    router.ROUTE_SOURCE_ACTIVE: ACTIVE_CHANNEL_NAME,
    router.ROUTE_SOURCE_SPARSE: CALIBRATED_CHANNEL_NAME,
}

#: The request fields the engine's ``exactStruct`` predicate compares.
ACTIVE_EXACT_CONTEXT_FIELDS: tuple[str, ...] = (
    "table_size",
    "raise_level",
    "family",
    "live_positions",
    "all_in_positions",
    "history",
)

#: Every top-level key a decision document carries.
RUNTIME_DECISION_REQUIRED_KEYS: tuple[str, ...] = (
    "schema",
    "contract_schema",
    "provider",
    "timing",
    "deterministic",
    "uses_hidden_hand",
    "uses_observed_result",
    "no_nearest_price_substitution",
    "no_nearest_context_substitution",
    "nearest_price_substituted",
    "nearest_context_substituted",
    "context_key",
    "request",
    "status",
    "usable",
    "abstain",
    "fail_closed",
    "fail_closed_reason",
    "route_source",
    "support_state",
    "uncertainty",
    "ood_status",
    "stratum",
    "analysis_admissible",
    "model_id",
    "model_hash",
    "probabilities",
    "legal_actions",
    "masked_actions",
    "probability_sum",
    "illegal_mass",
    "selected_action",
    "selected_sizing_bb",
    "sizing_provenance",
    "reason_codes",
    "signals",
    "routing",
    "deterministic_seed",
    "decision_canonical_sha256",
)

#: The frozen runtime contract fields (spec ``runtime_contract.required_fields``).
CONTRACT_REQUIRED_FIELDS: tuple[str, ...] = (
    "route_source",
    "model_id",
    "model_hash",
    "support_state",
    "uncertainty",
    "ood_status",
    "analysis_admissible",
)

#: Fields a route source must carry conditionally (spec ``runtime_contract``).
CONTRACT_CONDITIONAL_REQUIREMENTS: dict[str, str] = {
    "probabilities": "route_source != OOD_ABSTAIN",
    "sizing_provenance": "selected_action in {RAISE, JAM}",
}

#: Stable fail-closed codes of the provider.
FAIL_CLOSED_SPEC_UNAVAILABLE = "SPEC_UNAVAILABLE"
FAIL_CLOSED_SPEC_DRIFT = "SPEC_DIGEST_MISMATCH"
FAIL_CLOSED_SPEC_INVALID = "SPEC_INVALID"
FAIL_CLOSED_CONTRACT_MISMATCH = "CONTRACT_MISMATCH"
FAIL_CLOSED_TEST_SPLIT = "TEST_SPLIT_NOT_CONSUMABLE"
FAIL_CLOSED_REFUSED_SPLIT = "REFUSED_SPLIT"
FAIL_CLOSED_NEIGHBOUR_SUBSTITUTION = "NEAREST_NEIGHBOUR_SUBSTITUTION_REFUSED"
FAIL_CLOSED_ACTIVE_REFERENCE_UNAVAILABLE = "ACTIVE_REFERENCE_UNAVAILABLE"
FAIL_CLOSED_ACTIVE_REFERENCE_DRIFT = "ACTIVE_REFERENCE_DIGEST_MISMATCH"
FAIL_CLOSED_CALIBRATION_UNAVAILABLE = "CALIBRATION_REPORT_UNAVAILABLE"
FAIL_CLOSED_CALIBRATION_DRIFT = "CALIBRATION_REPORT_DIGEST_MISMATCH"
FAIL_CLOSED_ACTIVE_CELL_UNAVAILABLE = "ACTIVE_EXACT_CELL_UNAVAILABLE"
FAIL_CLOSED_CHANNEL_ABSTAINED = "CALIBRATED_CHANNEL_ABSTAINED"
FAIL_CLOSED_CHANNEL_REFUSED = "CALIBRATED_CHANNEL_REFUSED"
FAIL_CLOSED_ILLEGAL_SIZING_TARGET = "ILLEGAL_SIZING_TARGET"
FAIL_CLOSED_NO_LEGAL_ACTION = "NO_LEGAL_ACTION"
FAIL_CLOSED_UNKNOWN_ROUTE_SOURCE = "UNKNOWN_ROUTE_SOURCE"

FAIL_CLOSED_CODES: tuple[str, ...] = (
    FAIL_CLOSED_SPEC_UNAVAILABLE,
    FAIL_CLOSED_SPEC_DRIFT,
    FAIL_CLOSED_SPEC_INVALID,
    FAIL_CLOSED_CONTRACT_MISMATCH,
    FAIL_CLOSED_TEST_SPLIT,
    FAIL_CLOSED_REFUSED_SPLIT,
    FAIL_CLOSED_NEIGHBOUR_SUBSTITUTION,
    FAIL_CLOSED_ACTIVE_REFERENCE_UNAVAILABLE,
    FAIL_CLOSED_ACTIVE_REFERENCE_DRIFT,
    FAIL_CLOSED_CALIBRATION_UNAVAILABLE,
    FAIL_CLOSED_CALIBRATION_DRIFT,
    FAIL_CLOSED_ACTIVE_CELL_UNAVAILABLE,
    FAIL_CLOSED_CHANNEL_ABSTAINED,
    FAIL_CLOSED_CHANNEL_REFUSED,
    FAIL_CLOSED_ILLEGAL_SIZING_TARGET,
    FAIL_CLOSED_NO_LEGAL_ACTION,
    FAIL_CLOSED_UNKNOWN_ROUTE_SOURCE,
)

#: Reason codes the *runtime* (not the frozen gate) can add to a decision.
RUNTIME_REASON_DEFINITIONS: dict[str, str] = {
    FAIL_CLOSED_ACTIVE_CELL_UNAVAILABLE: (
        "the router routed to ACTIVE_STRONG_SUPPORT but the active Model A reference "
        "carries no exact cell for the request; the nearest active cell is never "
        "substituted"
    ),
    FAIL_CLOSED_CHANNEL_ABSTAINED: (
        "the calibrated generalized channel abstained (its own frozen OOD gate) while "
        "the hybrid router routed to the sparse channel; the decision abstains"
    ),
    FAIL_CLOSED_CHANNEL_REFUSED: (
        "the calibrated generalized channel refused the request (for example an illegal "
        "queried raise target); the decision abstains"
    ),
    FAIL_CLOSED_ILLEGAL_SIZING_TARGET: (
        "the queried raise target leaves the engine's legal raise window of the answer's "
        "action; the decision abstains instead of conditioning the distribution on a "
        "clamped sizing"
    ),
}

#: Declaration of the no-substitution contract of this provider.
NO_NEAREST_PRICE_SUBSTITUTION = True
NO_NEAREST_CONTEXT_SUBSTITUTION = True
#: Runtime evidence that no substitution happened (never set to ``True``).
NEAREST_PRICE_SUBSTITUTED = False
NEAREST_CONTEXT_SUBSTITUTED = False

#: Request keys that ask the provider for a substitution it always refuses.
SUBSTITUTION_REQUEST_KEYS: tuple[str, ...] = (
    "allow_nearest_neighbour",
    "allow_nearest_neighbor",
    "allow_nearest_price",
    "allow_nearest_context",
    "allow_nearest",
    "nearest_price_substituted",
    "nearest_context_substituted",
)

CANONICAL_DECIMALS = runtime.CANONICAL_DECIMALS
SIZING_WINDOW_TOLERANCE = runtime.SIZING_WINDOW_TOLERANCE

ChannelProvider = Callable[[Mapping[str, Any]], Mapping[str, Any]]


class HybridResponseRuntimeError(RuntimeError):
    """Fail-closed provider error carrying a stable machine-readable ``code``."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = str(code)
        self.message = str(message)
        #: The underlying channel code, when the refusal came from a channel.
        self.channel_code: str | None = None


class NeighbourSubstitutionRefused(HybridResponseRuntimeError):
    """A caller asked for a nearest-price / nearest-context substitution."""

    def __init__(self, message: str) -> None:
        super().__init__(FAIL_CLOSED_NEIGHBOUR_SUBSTITUTION, message)


class ActiveExactCellUnavailable(HybridResponseRuntimeError):
    """The active reference carries no exact cell for the queried context."""

    def __init__(self, message: str) -> None:
        super().__init__(FAIL_CLOSED_ACTIVE_CELL_UNAVAILABLE, message)


class CalibratedChannelRefused(HybridResponseRuntimeError):
    """The calibrated generalized channel refused or abstained on the request."""

    def __init__(
        self,
        message: str,
        *,
        code: str = FAIL_CLOSED_CHANNEL_REFUSED,
        channel_code: str | None = None,
    ) -> None:
        super().__init__(code, message)
        self.channel_code = channel_code


# ---------------------------------------------------------------------------
# content-addressing / canonicalisation helpers
# ---------------------------------------------------------------------------


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | Path) -> str:
    return sha256_bytes(Path(path).read_bytes())


def runtime_module_sha256() -> str:
    """Byte digest of this module, so a decision can pin the provider code."""
    return sha256_file(MODULE_PATH)


def canonical_json(document: Any) -> str:
    """Byte-stable JSON of a JSON-shaped document (sorted keys, ASCII, compact)."""
    return model.canonical_json(document)


def canonical_sha256(document: Any) -> str:
    """SHA-256 of the canonical JSON of ``document``."""
    return hashlib.sha256(canonical_json(document).encode("utf-8")).hexdigest()


def decision_canonical_sha256(document: Mapping[str, Any]) -> str:
    """Canonical digest of a decision document, excluding the digest field."""
    return runtime.decision_canonical_sha256(document)


def canonical_float(value: Any, *, decimals: int = CANONICAL_DECIMALS) -> float | None:
    """Quantise one number on the runtime's fixed decimal grid."""
    return runtime.canonical_float(value, decimals=decimals)


def canonical_floats(value: Any, *, decimals: int = CANONICAL_DECIMALS) -> Any:
    """Quantise every float of a JSON-shaped document (delegates to the runtime)."""
    return runtime.canonical_floats(value, decimals=decimals)


def canonical_legal_distribution(
    probabilities: Mapping[str, Any], legal: Sequence[str]
) -> tuple[dict[str, float], float, float]:
    """Quantised, re-closed legal distribution (delegates to the #421 runtime)."""
    return runtime.canonical_legal_distribution(probabilities, legal)


def _read_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _repo_relative(path: str | Path) -> str:
    """Environment-independent POSIX form of ``path`` (see the #421 runtime)."""
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = ROOT / resolved
    resolved = resolved.resolve()
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError:  # pragma: no cover - a path outside the repository
        return resolved.as_posix()


def _is_sha256(text: Any) -> bool:
    value = str(text or "")
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


# ---------------------------------------------------------------------------
# frozen spec consumption
# ---------------------------------------------------------------------------


def _spec_shape_errors(spec: Mapping[str, Any]) -> list[str]:
    """Structural validation of the frozen #423 preregistration document."""
    errors: list[str] = []
    if not isinstance(spec, Mapping):
        return ["spec must be a mapping"]
    if spec.get("schema") != SPEC_SCHEMA:
        errors.append(f"spec.schema must be {SPEC_SCHEMA!r}, got {spec.get('schema')!r}")
    if spec.get("frozen") is not True:
        errors.append("spec.frozen must be true")
    if int(spec.get("issue") or 0) != 423:
        errors.append(f"spec.issue must be 423, got {spec.get('issue')!r}")
    return errors


def _spec_contract_errors(spec: Mapping[str, Any]) -> list[str]:
    """The spec's declared surface must agree with the runtime's own declarations."""
    errors: list[str] = []
    sources = [
        str((entry or {}).get("id") or "")
        for entry in (spec.get("route_sources") or [])
        if isinstance(entry, Mapping)
    ]
    if sources != list(router.ROUTE_SOURCES):
        errors.append(
            f"spec.route_sources must be {list(router.ROUTE_SOURCES)}, got {sources}"
        )
    contract = spec.get("runtime_contract")
    if not isinstance(contract, Mapping):
        errors.append("spec.runtime_contract must be a mapping")
    else:
        if contract.get("schema") != CONTRACT_SCHEMA:
            errors.append(
                f"spec.runtime_contract.schema must be {CONTRACT_SCHEMA!r}, "
                f"got {contract.get('schema')!r}"
            )
        declared_required = {
            str((field or {}).get("name") or "")
            for field in (contract.get("fields") or [])
            if isinstance(field, Mapping) and field.get("required") is True
        }
        missing = [
            name for name in CONTRACT_REQUIRED_FIELDS if name not in declared_required
        ]
        if missing:
            errors.append(
                "spec.runtime_contract.fields must declare every required field as "
                f"required; missing {missing}"
            )
        if list(contract.get("required_fields") or []) != list(CONTRACT_REQUIRED_FIELDS):
            errors.append(
                "spec.runtime_contract.required_fields must be "
                f"{list(CONTRACT_REQUIRED_FIELDS)}, got "
                f"{list(contract.get('required_fields') or [])}"
            )
    split_policy = spec.get("split_policy")
    if not isinstance(split_policy, Mapping):
        errors.append("spec.split_policy must be a mapping")
    else:
        if list(split_policy.get("allowed_splits") or []) != ["TRAIN"]:
            errors.append("spec.split_policy.allowed_splits must be ['TRAIN']")
        refused = set(split_policy.get("refused_splits") or [])
        if not {"VALIDATION", "TEST"}.issubset(refused):
            errors.append("spec.split_policy.refused_splits must include VALIDATION and TEST")
    reasons = spec.get("reason_codes")
    if not isinstance(reasons, Mapping):
        errors.append("spec.reason_codes must be a mapping")
    else:
        if list(reasons.get("hard") or []) != list(model.OOD_HARD_REASONS):
            errors.append("spec.reason_codes.hard must match the frozen #421 hard reasons")
        if list(reasons.get("soft") or []) != list(model.OOD_SOFT_REASONS):
            errors.append("spec.reason_codes.soft must match the frozen #421 soft reasons")
    return errors


def _spec_errors(spec: Mapping[str, Any]) -> list[str]:
    """Every shape and contract error of a candidate spec document."""
    return _spec_shape_errors(spec) + _spec_contract_errors(spec)


def load_spec(
    path: str | Path | None = None,
    *,
    expected_sha256: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load and structurally validate the frozen spec, refusing any drift.

    The byte digest of the document must match ``expected_sha256`` (default: the
    repository's pinned :data:`SPEC_SHA256`).  The returned provenance carries
    the spec path, digest, canonical payload digest, freeze status and the
    manifest entry that pins it, so a consumer can verify the identity the
    decision was derived from.
    """
    target = Path(path) if path else SPEC_PATH
    if not target.exists():
        raise HybridResponseRuntimeError(
            FAIL_CLOSED_SPEC_UNAVAILABLE, f"the frozen spec is missing at {target}"
        )
    digest = sha256_file(target)
    expected = expected_sha256 if expected_sha256 is not None else SPEC_SHA256
    if _is_sha256(expected) and digest != expected:
        raise HybridResponseRuntimeError(
            FAIL_CLOSED_SPEC_DRIFT,
            f"the frozen spec drifted: {digest} != {expected} ({_repo_relative(target)})",
        )
    document = _read_json(target)
    shape_errors = _spec_shape_errors(document)
    if shape_errors:
        raise HybridResponseRuntimeError(
            FAIL_CLOSED_SPEC_INVALID,
            "invalid frozen spec: " + "; ".join(shape_errors),
        )
    contract_errors = _spec_contract_errors(document)
    if contract_errors:
        raise HybridResponseRuntimeError(
            FAIL_CLOSED_CONTRACT_MISMATCH,
            "the frozen spec disagrees with the runtime contract: "
            + "; ".join(contract_errors),
        )
    provenance: dict[str, Any] = {
        "path": _repo_relative(target),
        "sha256": digest,
        "schema": document.get("schema"),
        "canonical_payload_sha256": document.get("canonical_payload_sha256"),
        "issue": document.get("issue"),
        "status": document.get("status"),
        "frozen": document.get("frozen"),
        "frozen_at": (document.get("frozen_criteria") or {}).get("frozen_at"),
        "route_sources": [
            str((entry or {}).get("id") or "") for entry in (document.get("route_sources") or [])
        ],
        "split_policy": dict(document.get("split_policy") or {}),
        "required_fields": list(
            (document.get("runtime_contract") or {}).get("required_fields") or []
        ),
    }
    manifest = _manifest_provenance(target, digest)
    if manifest is not None:
        provenance["manifest"] = manifest
        entry = manifest.get("entry")
        if isinstance(entry, Mapping) and not manifest["entry_matches"]:
            raise HybridResponseRuntimeError(
                FAIL_CLOSED_SPEC_DRIFT,
                "the frozen spec disagrees with the manifest entry that pins it: "
                f"{digest} != {entry.get('sha256')}",
            )
    return document, provenance


def _manifest_provenance(target: Path, digest: str) -> dict[str, Any] | None:
    """The frozen manifest entry that pins ``target``, when the manifest is present."""
    if not MANIFEST_PATH.exists():
        return None
    manifest = _read_json(MANIFEST_PATH)
    entry: dict[str, Any] | None = None
    for item in manifest.get("derivation_inputs") or []:
        if not isinstance(item, Mapping) or item.get("path") is None:
            continue
        if _repo_relative(item.get("path")) == _repo_relative(target):
            entry = dict(item)
            break
    frozen = manifest.get("frozen_spec")
    manifest_digest = sha256_file(MANIFEST_PATH)
    return {
        "path": _repo_relative(MANIFEST_PATH),
        "sha256": manifest_digest,
        "pinned_sha256": MANIFEST_SHA256,
        "digest_matches": manifest_digest == MANIFEST_SHA256,
        "schema": manifest.get("schema"),
        "expected_schema": MANIFEST_SCHEMA,
        "schema_matches": manifest.get("schema") == MANIFEST_SCHEMA,
        "canonical_payload_sha256": manifest.get("canonical_payload_sha256"),
        "entry": entry,
        "entry_matches": entry is None or entry.get("sha256") == digest,
        "frozen_spec_matches": (
            not isinstance(frozen, Mapping) or frozen.get("sha256") == digest
        ),
    }


# ---------------------------------------------------------------------------
# active Model A exact-cell reference
# ---------------------------------------------------------------------------


def load_active_reference(
    path: str | Path | None = None,
    *,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    """Pin, load and index the active Model A reference (exact-cell lookups only)."""
    target = Path(path) if path else ACTIVE_MODEL_PATH
    if not target.exists():
        raise HybridResponseRuntimeError(
            FAIL_CLOSED_ACTIVE_REFERENCE_UNAVAILABLE,
            f"the active Model A reference is missing at {target}",
        )
    digest = sha256_file(target)
    expected = expected_sha256 if expected_sha256 is not None else ACTIVE_MODEL_SHA256
    if _is_sha256(expected) and digest != expected:
        raise HybridResponseRuntimeError(
            FAIL_CLOSED_ACTIVE_REFERENCE_DRIFT,
            "the active Model A reference drifted: "
            f"{digest} != {expected} ({_repo_relative(target)})",
        )
    document = _read_json(target)
    if not isinstance(document, Mapping):  # pragma: no cover - defensive
        raise HybridResponseRuntimeError(
            FAIL_CLOSED_ACTIVE_REFERENCE_UNAVAILABLE,
            f"{target} is not an active Model A document",
        )
    grid = list((document.get("hand_grid") or {}).get("classes") or [])
    return {
        "path": _repo_relative(target),
        "sha256": digest,
        "model_id": ACTIVE_MODEL_ID,
        "schema_version": document.get("schema_version"),
        "model_version": document.get("model_version"),
        "nodes": len(document.get("nodes") or []),
        "index": by_actor(list(document.get("nodes") or [])),
        "grid": grid,
        "weights": hand_weights(grid, (document.get("hand_grid") or {}).get("meta")),
    }


def _map_reference_action(name: Any) -> str | None:
    """Map an active Model A action label onto the response space (``LIMP``->``CALL``)."""
    text = str(name or "").strip().upper()
    if text == "LIMP":
        text = "CALL"
    return text if text in model.ACTION_INDEX else None


def active_exact_cell(
    reference: Mapping[str, Any], context: Mapping[str, Any]
) -> dict[str, Any] | None:
    """The active Model A node whose context is **exactly** the queried one.

    ``None`` means the active reference carries no exact cell for the request;
    the nearest active node is never returned.  When several nodes share the
    exact signature the most supported one wins (largest population support,
    ties broken by the stable node id), mirroring the ordering rule of the
    frozen engine matcher's exact branch without ever reaching its fallback.
    """
    actor = str(context.get("actor_position") or "")
    candidates = list((reference.get("index") or {}).get(actor) or [])
    matches = [
        node
        for node in candidates
        if runtime_exact(dict(node.get("context") or {}), dict(context))
    ]
    if not matches:
        return None
    matches.sort(
        key=lambda node: (
            -int((node.get("coverage") or {}).get("population_decisions") or 0),
            str(node.get("id") or node.get("canonical_key") or ""),
        )
    )
    return matches[0]


def active_probabilities(
    reference: Mapping[str, Any], node: Mapping[str, Any]
) -> dict[str, Any]:
    """Combo-weighted public action marginal of one active Model A node.

    The replication is the frozen #421/#423 comparator's mapping: the node's
    ``policy169`` policy is combined over the hand grid with the frozen combo
    weights and mapped onto the four response actions (``LIMP`` -> ``CALL``,
    non-response mass dropped and reported).  Nothing is substituted: the node
    is the exact cell the caller resolved.
    """
    raw: dict[str, float] = {}
    try:
        policy = decode_policy169(dict(node), list(reference.get("grid") or []))
        for hand, weight in (reference.get("weights") or {}).items():
            entry = policy.get(hand) or {}
            for action, value in entry.items():
                raw[str(action)] = raw.get(str(action), 0.0) + float(weight) * float(value)
        source = "POLICY169_COMBO_WEIGHTED"
    except (ValueError, TypeError, KeyError):
        frequencies = (node.get("population_model") or {}).get("frequencies") or {}
        raw = {str(action): float(value or 0.0) for action, value in frequencies.items()}
        source = "MARGINAL_FREQUENCY"

    mapped = {action: 0.0 for action in model.ACTIONS}
    for action, value in raw.items():
        target = _map_reference_action(action)
        if target is None:
            continue
        mapped[target] += max(0.0, float(value or 0.0))
    total = math.fsum(mapped.values())
    if total <= model.EPS:
        return {
            "available": False,
            "probabilities": None,
            "reason": "ACTIVE_NODE_EMPTY",
            "source": source,
        }
    probabilities = {action: mapped[action] / total for action in model.ACTIONS}
    return {
        "available": True,
        "probabilities": probabilities,
        "source": source,
        "dropped_non_response_mass": max(0.0, 1.0 - math.fsum(probabilities.values())),
    }


# ---------------------------------------------------------------------------
# request guards (split policy, substitution refusal)
# ---------------------------------------------------------------------------


def _row_split(context: Mapping[str, Any]) -> str:
    raw = context.get("split")
    return str(raw).strip().upper() if raw is not None else ""


def refuse_substitution_request(context: Mapping[str, Any]) -> None:
    """Refuse any caller request that asks for a nearest substitution."""
    for key in SUBSTITUTION_REQUEST_KEYS:
        if context.get(key):
            raise NeighbourSubstitutionRefused(
                f"the hybrid runtime never substitutes a neighbouring price or context "
                f"for the queried one (requested with {key!r})"
            )


def guard_split(
    context: Mapping[str, Any],
    *,
    refused_splits: Sequence[str] = ("VALIDATION", "TEST"),
) -> None:
    """Refuse a split the frozen policy does not consume, before any decision."""
    split = _row_split(context)
    refused = {str(value).strip().upper() for value in refused_splits}
    if split and split not in {"TRAIN"} and split in refused:
        if split == "TEST":
            raise HybridResponseRuntimeError(
                FAIL_CLOSED_TEST_SPLIT, f"split {split!r} is never consumable by the runtime"
            )
        raise HybridResponseRuntimeError(
            FAIL_CLOSED_REFUSED_SPLIT,
            f"split {split!r} is refused by the frozen #423 split policy (TRAIN only)",
        )


# ---------------------------------------------------------------------------
# the provider
# ---------------------------------------------------------------------------


class HybridResponseRuntime:
    """Fail-closed, deterministic hybrid provider over the frozen #423 surface."""

    def __init__(
        self,
        *,
        spec: Mapping[str, Any] | None = None,
        spec_path: str | Path | None = None,
        expected_spec_sha256: str | None = None,
        manifest_path: str | Path | None = None,
        calibration: Mapping[str, Any] | None = None,
        ood_report_path: str | Path | None = None,
        candidate: Any = None,
        candidate_id: str | None = None,
        generalized_runtime: runtime.GeneralizedResponseRuntime | None = None,
        active_reference: Mapping[str, Any] | None = None,
        active_reference_path: str | Path | None = None,
        expected_active_sha256: str | None = None,
        calibration_report_path: str | Path | None = None,
        expected_calibration_report_sha256: str | None = None,
        rule: str | router.RouteRule | None = None,
        channels: Mapping[str, ChannelProvider] | None = None,
        include_sizing: bool = True,
    ) -> None:
        if spec is not None:
            self.spec = dict(spec)
            shape_errors = _spec_shape_errors(self.spec)
            if shape_errors:
                raise HybridResponseRuntimeError(
                    FAIL_CLOSED_SPEC_INVALID,
                    "invalid supplied spec: " + "; ".join(shape_errors),
                )
            contract_errors = _spec_contract_errors(self.spec)
            if contract_errors:
                raise HybridResponseRuntimeError(
                    FAIL_CLOSED_CONTRACT_MISMATCH,
                    "the supplied spec disagrees with the runtime contract: "
                    + "; ".join(contract_errors),
                )
            self.spec_provenance: dict[str, Any] = {
                "path": None,
                "sha256": None,
                "schema": self.spec.get("schema"),
                "canonical_payload_sha256": self.spec.get("canonical_payload_sha256"),
                "issue": self.spec.get("issue"),
                "status": self.spec.get("status"),
                "frozen": self.spec.get("frozen"),
                "frozen_at": (self.spec.get("frozen_criteria") or {}).get("frozen_at"),
                "route_sources": [
                    str((entry or {}).get("id") or "")
                    for entry in (self.spec.get("route_sources") or [])
                ],
                "split_policy": dict(self.spec.get("split_policy") or {}),
                "required_fields": list(
                    (self.spec.get("runtime_contract") or {}).get("required_fields") or []
                ),
                "supplied_inline": True,
            }
            if manifest_path is not None:  # pragma: no cover - defensive
                raise HybridResponseRuntimeError(
                    FAIL_CLOSED_SPEC_INVALID,
                    "an inline spec cannot be combined with a manifest path",
                )
        else:
            self.spec, self.spec_provenance = load_spec(
                spec_path, expected_sha256=expected_spec_sha256
            )
        self.split_policy = dict(self.spec.get("split_policy") or {})
        self.refused_splits = tuple(
            str(value)
            for value in (
                self.split_policy.get("refused_splits") or ("VALIDATION", "TEST")
            )
        )
        self.rule = router.route_rule(rule)
        self.include_sizing = bool(include_sizing)
        # The router's calibration is the frozen #421 OOD report by default; a
        # caller-supplied report path is loaded with the model loader and then
        # validated by the router, so a malformed calibration fails closed.
        if calibration is not None:
            self.calibration = router.resolve_calibration(dict(calibration))
        elif ood_report_path is not None:
            self.calibration = router.resolve_calibration(
                model.load_ood_calibration(ood_report_path)
            )
        else:
            self.calibration = router.resolve_calibration(None)
        self.calibration_provenance = self._calibration_provenance(ood_report_path)
        self.generalized = (
            generalized_runtime
            if generalized_runtime is not None
            else runtime.GeneralizedResponseRuntime(
                candidate,
                candidate_id=candidate_id,
                ood_calibration=self.calibration,
            )
        )
        self.calibration_report = self._load_calibration_report(
            calibration_report_path, expected_calibration_report_sha256
        )
        self._active_reference = (
            dict(active_reference)
            if active_reference is not None
            else None
        )
        self._active_reference_path = active_reference_path
        self._expected_active_sha256 = expected_active_sha256
        self._channels = dict(channels or {})
        self._metadata: dict[str, Any] | None = None

    # -- identity / metadata ------------------------------------------------

    @property
    def active_reference(self) -> dict[str, Any]:
        """The active reference, loaded lazily (and pinned) on first use."""
        if self._active_reference is None:
            self._active_reference = load_active_reference(
                self._active_reference_path, expected_sha256=self._expected_active_sha256
            )
        return self._active_reference

    def _calibration_provenance(self, ood_report_path: str | Path | None) -> dict[str, Any]:
        path = Path(ood_report_path) if ood_report_path else model.DEFAULT_OOD_REPORT_PATH
        return {
            "path": _repo_relative(path),
            "sha256": sha256_file(path) if path.exists() else None,
            "schema": self.calibration.get("schema"),
            "canonical_payload_sha256": self.calibration.get("canonical_payload_sha256"),
            "gate_schema": self.calibration.get("gate_schema"),
            "statuses": list(self.calibration.get("statuses") or []),
            "consumed_splits": list(
                (self.calibration.get("provenance") or {}).get("consumed_splits") or []
            ),
        }

    def _load_calibration_report(
        self,
        path: str | Path | None,
        expected_sha256: str | None,
    ) -> dict[str, Any]:
        target = Path(path) if path else CALIBRATION_REPORT_PATH
        if not target.exists():
            raise HybridResponseRuntimeError(
                FAIL_CLOSED_CALIBRATION_UNAVAILABLE,
                f"the frozen #423 calibration report is missing at {target}",
            )
        digest = sha256_file(target)
        expected = expected_sha256 if expected_sha256 is not None else CALIBRATION_REPORT_SHA256
        if _is_sha256(expected) and digest != expected:
            raise HybridResponseRuntimeError(
                FAIL_CLOSED_CALIBRATION_DRIFT,
                "the frozen #423 calibration report drifted: "
                f"{digest} != {expected} ({_repo_relative(target)})",
            )
        document = _read_json(target)
        if (
            not isinstance(document, Mapping)
            or document.get("schema") != CALIBRATION_REPORT_SCHEMA
        ):  # pragma: no cover - defensive
            raise HybridResponseRuntimeError(
                FAIL_CLOSED_CALIBRATION_UNAVAILABLE,
                f"{target} is not a {CALIBRATION_REPORT_SCHEMA} document",
            )
        return {
            "path": _repo_relative(target),
            "sha256": digest,
            "schema": document.get("schema"),
            "canonical_payload_sha256": document.get("canonical_payload_sha256"),
            "retained_architecture": document.get("retained_architecture"),
            "retained_method": document.get("retained_method"),
            "headline_architecture": (document.get("harness") or {}).get("headline_architecture"),
            "consumed_splits": list((document.get("scope") or {}).get("consumed_splits") or []),
            "refused_splits": list((document.get("scope") or {}).get("refused_splits") or []),
            "guards": dict(document.get("guards") or {}),
        }

    def metadata(self) -> dict[str, Any]:
        """Provider identity: the frozen identities every decision is bound to."""
        if self._metadata is not None:
            return self._metadata
        self._metadata = {
            "schema": HYBRID_RUNTIME_PROVIDER_SCHEMA,
            "provider_kind": "HYBRID_PREFLOP_RESPONSE_RUNTIME",
            "decision_schema": HYBRID_RUNTIME_DECISION_SCHEMA,
            "contract_schema": CONTRACT_SCHEMA,
            "route_sources": list(router.ROUTE_SOURCES),
            "support_states": [
                router.SUPPORT_STATE_STRONG,
                router.SUPPORT_STATE_SPARSE,
                router.SUPPORT_STATE_ABSTAIN,
            ],
            "action_space": list(model.ACTIONS),
            "aggressive_actions": list(model.AGGRESSIVE_ACTIONS),
            "rule": self.rule.as_document(),
            "spec": self.spec_provenance,
            "ood_calibration": self.calibration_provenance,
            "generalized_calibration_report": self.calibration_report,
            "active_reference": {
                "path": self.active_reference.get("path"),
                "sha256": self.active_reference.get("sha256"),
                "model_id": self.active_reference.get("model_id"),
                "model_version": self.active_reference.get("model_version"),
                "nodes": self.active_reference.get("nodes"),
                "exact_context_fields": list(ACTIVE_EXACT_CONTEXT_FIELDS),
                "lookup": "exact_cell_only_never_the_nearest_node",
            },
            "runtime": self._runtime_identity(),
            "guarantees": self.guarantees(),
        }
        return self._metadata

    def audit(self) -> dict[str, Any]:
        return {
            "deterministic": True,
            "stdlib_only": True,
            "nearest_price_substituted": NEAREST_PRICE_SUBSTITUTED,
            "nearest_context_substituted": NEAREST_CONTEXT_SUBSTITUTED,
            "active_reference_exact_cell_only": True,
            "test_consumed": False,
            "validation_consumed": False,
            "active_model_pointer_mutated": False,
            "split_policy": dict(self.split_policy),
            "fail_closed_codes": list(FAIL_CLOSED_CODES),
        }

    def guarantees(self) -> dict[str, Any]:
        return {
            "deterministic": True,
            "byte_stable": True,
            "stdlib_only": True,
            "canonical_decimal_grid": CANONICAL_DECIMALS,
            "interpreter_independent_bytes": True,
            "illegal_mass": 0.0,
            "probability_sum": 1.0,
            "legal_masking": True,
            "fail_closed_on_ood": True,
            "fail_closed_on_refused_split": True,
            "fail_closed_on_spec_drift": True,
            "no_nearest_price_substitution": NO_NEAREST_PRICE_SUBSTITUTION,
            "no_nearest_context_substitution": NO_NEAREST_CONTEXT_SUBSTITUTION,
            "active_branch_requires_an_exact_active_cell": True,
            "sizing_provenance_on_raise_or_jam": True,
        }

    def _runtime_identity(self) -> dict[str, Any]:
        return {
            "module_path": "tools/preflop/hybrid_response_runtime.py",
            "module_sha256": runtime_module_sha256(),
            "schema": HYBRID_RUNTIME_DECISION_SCHEMA,
            "router_module": "tools/preflop/hybrid_response_router.py",
            "router_module_sha256": sha256_file(
                ROOT / "tools/preflop/hybrid_response_router.py"
            ),
        }

    # -- channel providers --------------------------------------------------

    def active_channel(self, context: Mapping[str, Any]) -> dict[str, Any]:
        """The ``ACTIVE_STRONG_SUPPORT`` answer: the active exact cell, or refused.

        The exact cell is resolved by :func:`active_exact_cell`; when the active
        reference carries no exact cell the provider refuses fail-closed with
        ``ACTIVE_EXACT_CELL_UNAVAILABLE`` instead of reading the nearest active
        node.
        """
        reference = self.active_reference
        node = active_exact_cell(reference, context)
        if node is None:
            raise ActiveExactCellUnavailable(
                "the active Model A reference carries no exact cell for context "
                f"{model.ood_exact_context_key(context)!r} (actor "
                f"{context.get('actor_position')!r}); the nearest active node is never "
                "substituted"
            )
        marginal = active_probabilities(reference, node)
        if not marginal.get("available"):
            raise ActiveExactCellUnavailable(
                "the exact active cell "
                f"{node.get('id')!r} carries no legal response mass "
                f"({marginal.get('reason')})"
            )
        cell = {
            "node_id": node.get("id"),
            "canonical_key": node.get("canonical_key"),
            "support": int((node.get("coverage") or {}).get("population_decisions") or 0),
            "exact": True,
            "policy_source": marginal.get("source"),
            "dropped_non_response_mass": canonical_float(
                marginal.get("dropped_non_response_mass")
            ),
            "probability_model_id": reference.get("model_id"),
            "probability_model_hash": reference.get("sha256"),
        }
        return {
            "route_source": router.ROUTE_SOURCE_ACTIVE,
            "channel": ACTIVE_CHANNEL_NAME,
            "model_id": ACTIVE_MODEL_ID,
            "model_hash": reference.get("sha256"),
            "probabilities": marginal["probabilities"],
            "cell": cell,
        }

    def calibrated_channel(self, context: Mapping[str, Any]) -> dict[str, Any]:
        """The ``GENERALIZED_SPARSE_IN_DOMAIN`` answer: the calibrated #421 channel."""
        try:
            document = self.generalized.resolve(context)
        except runtime.GeneralizedResponseRuntimeError as error:
            code = (
                FAIL_CLOSED_ILLEGAL_SIZING_TARGET
                if error.code == runtime.FAIL_CLOSED_ILLEGAL_SIZING
                else FAIL_CLOSED_CHANNEL_REFUSED
            )
            raise CalibratedChannelRefused(
                f"the calibrated generalized channel refused the request: {error.message}",
                code=code,
                channel_code=error.code,
            ) from error
        if not document.get("usable"):
            raise CalibratedChannelRefused(
                "the calibrated generalized channel abstained on the request "
                f"(gate status {document.get('ood', {}).get('status')!r})",
                code=FAIL_CLOSED_CHANNEL_ABSTAINED,
                channel_code=runtime.STATUS_ABSTAIN,
            )
        candidate = document.get("provenance", {}).get("candidate", {})
        cell = {
            "candidate_id": candidate.get("candidate_id"),
            "canonical_payload_sha256": candidate.get("canonical_payload_sha256"),
            "context_key": document.get("context_key"),
            "support": int((document.get("prediction") or {}).get("support") or 0),
            "exact": False,
            "sizing_status": (document.get("sizing") or {}).get("status"),
            "probability_model_id": GENERALIZED_MODEL_ID,
            "probability_model_hash": candidate.get("canonical_payload_sha256"),
        }
        return {
            "route_source": router.ROUTE_SOURCE_SPARSE,
            "channel": CALIBRATED_CHANNEL_NAME,
            "model_id": GENERALIZED_MODEL_ID,
            "model_hash": candidate.get("canonical_payload_sha256"),
            "probabilities": document.get("action_probabilities"),
            "cell": cell,
            "sizing": document.get("sizing"),
        }

    def _provider(self, route_source: str) -> ChannelProvider:
        if route_source in self._channels:
            return self._channels[route_source]
        if route_source == router.ROUTE_SOURCE_ACTIVE:
            return self.active_channel
        if route_source == router.ROUTE_SOURCE_SPARSE:
            return self.calibrated_channel
        raise HybridResponseRuntimeError(
            FAIL_CLOSED_UNKNOWN_ROUTE_SOURCE,
            f"no provider is declared for route source {route_source!r}",
        )

    # -- sizing provenance --------------------------------------------------

    def _policy_config(self) -> Mapping[str, Any] | None:
        candidate = getattr(self.generalized, "candidate", None)
        if isinstance(candidate, Mapping):
            config = candidate.get("config")
            if isinstance(config, Mapping):
                return config
        return None

    def _window_legality(self, context: Mapping[str, Any], action: str) -> dict[str, Any] | None:
        config = self._policy_config()
        if config is None:  # pragma: no cover - a synthetic provider without a candidate
            return None
        target = router.queried_sizing_target(context)
        window = model.raise_sizing_window(context, action=action, config=config)
        declaration: dict[str, Any] = {
            "schema": model.RAISE_SIZING_WINDOW_SCHEMA,
            "action": action,
            "queried": target is not None,
            "queried_target_bb": canonical_float(target),
            "inside_legal_window": None,
            "violation": None,
            "policy": runtime.SIZING_WINDOW_POLICY,
            "substituted": False,
            "legal_window": canonical_floats(window),
        }
        if target is None:
            return declaration
        if window.get("fail_closed"):
            declaration["inside_legal_window"] = False
            declaration["violation"] = runtime.SIZING_WINDOW_UNVERIFIED
            return declaration
        floor = float(window["floor_bb"])
        cap = float(window["cap_bb"])
        if target < floor - SIZING_WINDOW_TOLERANCE:
            declaration["inside_legal_window"] = False
            declaration["violation"] = runtime.SIZING_WINDOW_TARGET_BELOW_MINIMUM
        elif target > cap + SIZING_WINDOW_TOLERANCE:
            declaration["inside_legal_window"] = False
            declaration["violation"] = runtime.SIZING_WINDOW_TARGET_ABOVE_CAP
        else:
            declaration["inside_legal_window"] = True
        return declaration

    def _conditional_sizing(
        self, context: Mapping[str, Any], action: str, answer: Mapping[str, Any]
    ) -> dict[str, Any] | None:
        """The conditional raise-sizing answer of an aggressive branch, or ``None``."""
        if not self.include_sizing:
            return None
        supplied = answer.get("sizing")
        if isinstance(supplied, Mapping):
            return canonical_floats(supplied)
        candidate = getattr(self.generalized, "candidate", None)
        if not isinstance(candidate, Mapping):  # pragma: no cover - synthetic provider
            return None
        try:
            return canonical_floats(model.raise_sizing_query(candidate, context, action=action))
        except (model.GeneralizedResponseModelError, ValueError, TypeError, KeyError):
            # A sizing request the frozen channel cannot answer leaves the
            # provenance without a conditional sizing answer; the aggressive
            # branch is then refused by the router for want of a target.
            return None

    def sizing_provenance(
        self,
        context: Mapping[str, Any],
        *,
        answer: Mapping[str, Any],
        selected_action: str,
    ) -> dict[str, Any] | None:
        """Machine-readable provenance of a RAISE / JAM answer.

        The provenance always declares the **exact** queried target (never a
        neighbouring price), the refusal flags, the engine's legal raise window
        and its verdict, the conditional sizing answer and the identity of the
        sizing channel that produced it.  It is emitted for every aggressive
        selection, as the frozen runtime contract requires.
        """
        if selected_action not in model.AGGRESSIVE_ACTIONS:
            return None
        queried = router.queried_sizing_target(context)
        conditioning, conditioning_source = self._conditioning_target(
            context, answer=answer, selected_action=selected_action
        )
        window = self._window_legality(context, selected_action)
        sizing = self._conditional_sizing(context, selected_action, answer)
        candidate = getattr(self.generalized, "candidate", None)
        sizing_model_id = GENERALIZED_MODEL_ID if isinstance(candidate, Mapping) else NO_MODEL_ID
        sizing_model_hash = (
            getattr(self.generalized, "candidate_sha256", None)
            if isinstance(candidate, Mapping)
            else None
        )
        selected_sizing = None
        if isinstance(sizing, Mapping) and sizing.get("status") == "RESOLVED":
            selected_sizing = runtime._representative_sizing(sizing)  # noqa: SLF001 - frozen helper
        return {
            "schema": SIZING_PROVENANCE_SCHEMA,
            "action": selected_action,
            "route_source": answer.get("route_source"),
            "probability_channel": answer.get("channel"),
            "probability_model_id": answer.get("model_id"),
            "probability_model_hash": answer.get("model_hash"),
            "sizing_channel": SIZING_CHANNEL_ID if isinstance(candidate, Mapping) else None,
            "sizing_model_id": sizing_model_id,
            "sizing_model_hash": sizing_model_hash,
            "sizing_module": SIZING_MODULE_PATH,
            "queried": queried is not None,
            "queried_target_total_bb": canonical_float(queried),
            "target_total_bb": canonical_float(conditioning),
            "conditioning_target_source": conditioning_source,
            "sizing_ratio": canonical_float(self._sizing_ratio(context)),
            "no_nearest_price_substitution": NO_NEAREST_PRICE_SUBSTITUTION,
            "no_nearest_context_substitution": NO_NEAREST_CONTEXT_SUBSTITUTION,
            "nearest_price_substituted": NEAREST_PRICE_SUBSTITUTED,
            "nearest_context_substituted": NEAREST_CONTEXT_SUBSTITUTED,
            "legal_window": None if window is None else window["legal_window"],
            "inside_legal_window": None if window is None else window["inside_legal_window"],
            "violation": None if window is None else window["violation"],
            "window_policy": None if window is None else window["policy"],
            "conditional_sizing_status": (
                None if not isinstance(sizing, Mapping) else sizing.get("status")
            ),
            "conditional_sizing": sizing,
            "selected_sizing_bb": selected_sizing,
            "exact_cell": dict(answer.get("cell") or {}),
        }

    def _conditioning_target(
        self,
        context: Mapping[str, Any],
        *,
        answer: Mapping[str, Any],
        selected_action: str,
    ) -> tuple[float | None, str]:
        """The exact target an aggressive answer is conditioned on.

        The queried target wins when the caller supplied one (so the answer is
        never conditioned on a neighbouring price); otherwise the target is the
        representative of the sizing channel's own answer -- a value the model
        produced and verified, never an invented one.
        """
        queried = router.queried_sizing_target(context)
        if queried is not None:
            return queried, "QUERIED_EXACT"
        sizing = self._conditional_sizing(context, selected_action, answer)
        if isinstance(sizing, Mapping) and sizing.get("status") == "RESOLVED":
            return runtime._representative_sizing(sizing), "CONDITIONAL_SIZING"  # noqa: SLF001
        return None, "UNRESOLVED"

    def _sizing_ratio(self, context: Mapping[str, Any]) -> float | None:
        value = router.resolve_numeric_axis(context, model.OOD_SIZING_AXIS)
        return value

    # -- the decision surface -----------------------------------------------

    def _abstention_reason_codes(self, fail_closed_reason: str | None) -> list[str]:
        if fail_closed_reason is None or fail_closed_reason not in RUNTIME_REASON_DEFINITIONS:
            return []
        return [fail_closed_reason]

    def resolve(
        self,
        context: Mapping[str, Any],
        *,
        strict: bool = False,
    ) -> dict[str, Any]:
        """Resolve one public preflop request into a machine-readable decision.

        The context is validated against the frozen split policy and the
        no-substitution contract before a single signal is computed, routed by
        the frozen router, answered by the route's channel and canonicalised onto
        the runtime's fixed decimal grid.  When the frozen router abstains, or
        when the selected channel refuses, the decision abstains fail-closed and
        (when ``strict``) the refusal is re-raised.
        """
        if not isinstance(context, Mapping):
            raise TypeError("context must be a mapping")
        refuse_substitution_request(context)
        guard_split(context, refused_splits=self.refused_splits)

        routing = router.route(
            context,
            calibration=self.calibration,
            model_candidate=self._model_candidate(),
            rule=self.rule,
        )
        routed_source = str(routing["route_source"])
        fail_closed_reason: str | None = None
        detail: dict[str, Any] | None = None
        answer: dict[str, Any] | None = None
        channel: dict[str, Any] | None = None

        if routed_source != router.ROUTE_SOURCE_ABSTAIN:
            channel_provider = self._provider(routed_source)
            try:
                answer = dict(channel_provider(context))
                answer.setdefault("route_source", routed_source)
                answer.setdefault("channel", DEFAULT_CHANNEL_NAME[routed_source])
            except HybridResponseRuntimeError as error:
                fail_closed_reason = error.code
                detail = {
                    "channel_error": error.message,
                    "channel_error_code": error.channel_code,
                }
                if strict:
                    raise
            if answer is not None:
                legal = router.legal_response_actions(context)
                if not legal:
                    fail_closed_reason = FAIL_CLOSED_NO_LEGAL_ACTION
                    detail = {"channel_error": "context carries no legal response action"}
                    if strict:
                        raise HybridResponseRuntimeError(
                            FAIL_CLOSED_NO_LEGAL_ACTION,
                            "context carries no legal response action",
                        )
                else:
                    try:
                        channel = router.attach_channel_answer(
                            context,
                            route_source=routed_source,
                            channel=self._channel_payload(context, answer),
                        )
                    except router.RouterError as error:
                        fail_closed_reason = error.code
                        detail = {"channel_error": str(error)}
                        if strict:
                            raise HybridResponseRuntimeError(error.code, str(error)) from error
                    # An aggressive answer conditions its distribution on the queried
                    # raise target; a target that leaves the engine's legal window
                    # (or a window that cannot be verified) abstains fail-closed
                    # instead of answering with a clamped sizing gain.
                    if (
                        channel is not None
                        and channel["selected_action"] in model.AGGRESSIVE_ACTIONS
                    ):
                        window = self._window_legality(context, channel["selected_action"])
                        if (
                            window is not None
                            and window["queried"]
                            and window["inside_legal_window"] is not True
                        ):
                            fail_closed_reason = FAIL_CLOSED_ILLEGAL_SIZING_TARGET
                            detail = {
                                "channel_error": (
                                    "the queried raise target "
                                    f"{window['queried_target_bb']} is outside the legal window "
                                    f"of {channel['selected_action']} ({window['violation']})"
                                ),
                                "channel_error_code": window["violation"],
                            }
                            channel = None
                            if strict:
                                raise HybridResponseRuntimeError(
                                    FAIL_CLOSED_ILLEGAL_SIZING_TARGET,
                                    str(detail["channel_error"]),
                                )

        document = self._decision_document(
            context,
            routing=routing,
            routed_source=routed_source,
            channel=channel,
            answer=answer,
            fail_closed_reason=fail_closed_reason,
            detail=detail,
        )
        return document

    def _model_candidate(self) -> Mapping[str, Any] | None:
        candidate = getattr(self.generalized, "candidate", None)
        return candidate if isinstance(candidate, Mapping) else None

    def _channel_payload(
        self, context: Mapping[str, Any], answer: Mapping[str, Any]
    ) -> dict[str, Any]:
        """The router channel answer: probabilities plus an exact-target provenance."""
        selected_probe = None
        declared = answer.get("probabilities") or {}
        legal = router.legal_response_actions(context)
        if legal:
            selected_probe = max(
                legal,
                key=lambda action: (
                    float(declared.get(action) or 0.0),
                    -model.ACTIONS.index(action),
                ),
            )
        payload: dict[str, Any] = {
            "model_id": answer.get("model_id"),
            "model_hash": answer.get("model_hash"),
            "probabilities": dict(declared),
        }
        if selected_probe in model.AGGRESSIVE_ACTIONS:
            provenance = self._channel_sizing_provenance(
                context, answer=answer, selected_action=selected_probe
            )
            if provenance is not None:
                payload["sizing_provenance"] = provenance
        return payload

    def _channel_sizing_provenance(
        self,
        context: Mapping[str, Any],
        *,
        answer: Mapping[str, Any],
        selected_action: str,
    ) -> dict[str, Any]:
        """The minimal sizing provenance the frozen router validates.

        It carries the **exact** queried target and the no-substitution
        declaration; the full sizing provenance of the emitted decision is
        rebuilt by :meth:`sizing_provenance`.
        """
        supplied = answer.get("sizing_provenance")
        if isinstance(supplied, Mapping):
            provenance = canonical_floats(dict(supplied))
            provenance.setdefault("no_nearest_price_substitution", NO_NEAREST_PRICE_SUBSTITUTION)
            provenance.setdefault("nearest_price_substituted", NEAREST_PRICE_SUBSTITUTED)
            provenance.setdefault("nearest_context_substituted", NEAREST_CONTEXT_SUBSTITUTED)
            return provenance
        target, source = self._conditioning_target(
            context, answer=answer, selected_action=selected_action
        )
        return {
            "target_total_bb": canonical_float(target),
            "conditioning_target_source": source,
            "no_nearest_price_substitution": NO_NEAREST_PRICE_SUBSTITUTION,
            "nearest_price_substituted": NEAREST_PRICE_SUBSTITUTED,
            "nearest_context_substituted": NEAREST_CONTEXT_SUBSTITUTED,
        }

    # -- document ------------------------------------------------------------

    def _decision_document(
        self,
        context: Mapping[str, Any],
        *,
        routing: Mapping[str, Any],
        routed_source: str,
        channel: Mapping[str, Any] | None,
        answer: Mapping[str, Any] | None,
        fail_closed_reason: str | None,
        detail: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        signals = dict(routing["signals"])
        abstain = routed_source == router.ROUTE_SOURCE_ABSTAIN or channel is None
        effective_source = (
            router.ROUTE_SOURCE_ABSTAIN if abstain else str(routing["route_source"])
        )
        if routed_source == router.ROUTE_SOURCE_ABSTAIN:
            fail_closed_reason = fail_closed_reason or runtime.OOD_ABSTAIN_REASON
        if channel is None:
            probabilities = None
            selected_action = None
            sizing_provenance = None
            model_id = NO_MODEL_ID
            model_hash = None
            legal_actions = router.legal_response_actions(context)
            masked = [action for action in model.ACTIONS if action not in set(legal_actions)]
            probability_sum = None
            illegal_mass = None
            selected_sizing = None
        else:
            probabilities = dict(channel["probabilities"])
            selected_action = channel["selected_action"]
            model_id = channel["model_id"]
            model_hash = channel["model_hash"]
            legal_actions = list(channel["legal_actions"])
            masked = [action for action in model.ACTIONS if action not in set(legal_actions)]
            probability_sum = channel["probability_sum"]
            illegal_mass = channel["illegal_mass"]
            sizing_provenance = (
                self.sizing_provenance(
                    context, answer=answer or {}, selected_action=selected_action
                )
                if selected_action in model.AGGRESSIVE_ACTIONS
                else None
            )
            selected_sizing = (
                None if sizing_provenance is None else sizing_provenance["selected_sizing_bb"]
            )
        uncertainty = "HIGH" if signals["soft_reasons"] else "NONE"
        ood_status = signals["ood_status"]
        if abstain:
            status = runtime.STATUS_ABSTAIN
        elif uncertainty == "HIGH":
            status = runtime.STATUS_HIGH_UNCERTAINTY
        else:
            status = runtime.STATUS_RESOLVED
        analysis_admissible = bool(
            not abstain
            and probabilities is not None
            and (selected_action not in model.AGGRESSIVE_ACTIONS or sizing_provenance is not None)
        )
        reason_catalog = {code: router.REASON_CLASS[code] for code in signals["reasons"]}
        runtime_reasons = self._abstention_reason_codes(fail_closed_reason)
        document: dict[str, Any] = {
            "schema": HYBRID_RUNTIME_DECISION_SCHEMA,
            "contract_schema": CONTRACT_SCHEMA,
            "provider": self.metadata(),
            "timing": router.TIMING_BEFORE_ACTION,
            "deterministic": True,
            "uses_hidden_hand": False,
            "uses_observed_result": False,
            "no_nearest_price_substitution": NO_NEAREST_PRICE_SUBSTITUTION,
            "no_nearest_context_substitution": NO_NEAREST_CONTEXT_SUBSTITUTION,
            "nearest_price_substituted": NEAREST_PRICE_SUBSTITUTED,
            "nearest_context_substituted": NEAREST_CONTEXT_SUBSTITUTED,
            "context_key": signals["context_key"],
            "request": router._request_view(context),  # noqa: SLF001 - the router request echo
            "status": status,
            "usable": not abstain,
            "abstain": abstain,
            "fail_closed": abstain,
            "fail_closed_reason": fail_closed_reason if abstain else None,
            "route_source": effective_source,
            "routed_source": routed_source,
            "support_state": router.SUPPORT_STATE_OF_ROUTE[effective_source],
            "uncertainty": uncertainty,
            "ood_status": ood_status,
            "stratum": signals["stratum"],
            "analysis_admissible": analysis_admissible,
            "model_id": model_id,
            "model_hash": model_hash,
            "probabilities": probabilities,
            "P(FOLD)": None if probabilities is None else probabilities["FOLD"],
            "P(CALL)": None if probabilities is None else probabilities["CALL"],
            "P(RAISE)": None if probabilities is None else probabilities["RAISE"],
            "P(JAM)": None if probabilities is None else probabilities["JAM"],
            "legal_actions": legal_actions,
            "masked_actions": masked,
            "probability_sum": probability_sum,
            "illegal_mass": illegal_mass,
            "selected_action": selected_action,
            "selected_sizing_bb": selected_sizing,
            "sizing_provenance": sizing_provenance,
            "reason_codes": {
                "hard": list(signals["hard_reasons"]),
                "soft": list(signals["soft_reasons"]),
                "all": list(signals["reasons"]),
                "catalog": reason_catalog,
                "runtime": runtime_reasons,
                "runtime_catalog": {
                    code: RUNTIME_REASON_DEFINITIONS[code] for code in runtime_reasons
                },
                "abstaining": list(
                    ((self.spec.get("reason_codes") or {}).get("abstaining")) or []
                ),
            },
            "signals": signals,
            "routing": dict(routing),
            "routing_canonical_sha256": routing.get("decision_canonical_sha256"),
            "channel": (
                None
                if channel is None
                else {
                    "channel": (answer or {}).get("channel"),
                    "cell": dict((answer or {}).get("cell") or {}),
                    "probability_sum": channel["probability_sum"],
                    "illegal_mass": channel["illegal_mass"],
                    "legal_actions": list(channel["legal_actions"]),
                }
            ),
            "detail": dict(detail or {}) or None,
            "deterministic_seed": getattr(self.generalized, "seed", None),
        }
        document = canonical_floats(document)
        routing_canonical = canonical_floats(dict(document["routing"]))
        routing_canonical["decision_canonical_sha256"] = router.canonical_sha256(
            {
                key: value
                for key, value in routing_canonical.items()
                if key != "decision_canonical_sha256"
            }
        )
        document["routing"] = routing_canonical
        document["routing_canonical_sha256"] = routing_canonical["decision_canonical_sha256"]
        document["decision_canonical_sha256"] = decision_canonical_sha256(document)
        return document


# ---------------------------------------------------------------------------
# module-level entry points
# ---------------------------------------------------------------------------


@lru_cache(maxsize=4)
def load_runtime(
    spec_path: str | None = None,
    expected_spec_sha256: str | None = None,
    ood_report_path: str | None = None,
    active_reference_path: str | None = None,
) -> HybridResponseRuntime:
    """Cached provider handle for the frozen spec and the frozen channels."""
    return HybridResponseRuntime(
        spec_path=spec_path,
        expected_spec_sha256=expected_spec_sha256,
        ood_report_path=ood_report_path,
        active_reference_path=active_reference_path,
    )


def clear_runtime_caches() -> None:
    """Drop the memoized provider handles (used by tests that tamper with files)."""
    load_runtime.cache_clear()
    runtime.clear_runtime_caches()


def resolve_hybrid_response(
    context: Mapping[str, Any],
    *,
    runtime_handle: HybridResponseRuntime | None = None,
    spec_path: str | None = None,
    expected_spec_sha256: str | None = None,
    ood_report_path: str | None = None,
    active_reference_path: str | None = None,
    spec: Mapping[str, Any] | None = None,
    calibration: Mapping[str, Any] | None = None,
    active_reference: Mapping[str, Any] | None = None,
    candidate: Any = None,
    candidate_id: str | None = None,
    generalized_runtime: runtime.GeneralizedResponseRuntime | None = None,
    rule: str | router.RouteRule | None = None,
    channels: Mapping[str, ChannelProvider] | None = None,
    include_sizing: bool = True,
    strict: bool = False,
) -> dict[str, Any]:
    """Resolve one public preflop request with the hybrid runtime provider."""
    injections = any(
        value is not None
        for value in (
            spec,
            calibration,
            active_reference,
            candidate,
            generalized_runtime,
            channels,
        )
    ) or spec_path is not None or ood_report_path is not None or active_reference_path is not None
    if runtime_handle is None:
        if injections:
            runtime_handle = HybridResponseRuntime(
                spec=spec,
                spec_path=spec_path,
                expected_spec_sha256=expected_spec_sha256,
                ood_report_path=ood_report_path,
                calibration=calibration,
                active_reference=active_reference,
                active_reference_path=active_reference_path,
                candidate=candidate,
                candidate_id=candidate_id,
                generalized_runtime=generalized_runtime,
                rule=rule,
                channels=channels,
                include_sizing=include_sizing,
            )
        else:
            runtime_handle = load_runtime(None, expected_spec_sha256, None, None)
    return runtime_handle.resolve(context, strict=strict)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Resolve one preflop request with the #423 hybrid runtime provider."
    )
    parser.add_argument("--context", help="inline JSON context document")
    parser.add_argument("--context-file", help="path to a JSON context document")
    parser.add_argument("--spec", help="path to the frozen #423 spec")
    parser.add_argument("--rule", default=router.DEFAULT_RULE_ID, help="route rule id")
    parser.add_argument("--no-sizing", action="store_true", help="skip the conditional sizing")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="re-raise a channel-level refusal instead of emitting an abstention",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.context and args.context_file:
        parser.error("--context and --context-file are mutually exclusive")
    if args.context_file:
        context = _read_json(args.context_file)
    elif args.context:
        context = json.loads(args.context)
    else:
        parser.error("one of --context or --context-file is required")
    handle = HybridResponseRuntime(
        spec_path=args.spec,
        rule=args.rule,
        include_sizing=not args.no_sizing,
    )
    document = handle.resolve(context, strict=args.strict)
    print(json.dumps(document, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False))
    return 0


if __name__ == "__main__":  # pragma: no cover - thin CLI wrapper
    raise SystemExit(main())

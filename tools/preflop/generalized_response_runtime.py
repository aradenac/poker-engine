#!/usr/bin/env python3
"""#421 T9 runtime provider: generalized adverse-response fail-closed resolution.

This module turns the *research* surface of
:mod:`tools.preflop.generalized_response_model` into a single, machine-readable
decision document that a consumer (for example the #367 real-ISO provider) can
read without re-deriving the model contract:

``resolve_generalized_response(context)``
    * loads the candidate **by id or by content hash** and refuses any
      candidate/hash mismatch *before* evaluating anything;
    * evaluates the fitted function **directly** at the queried public context
      (price / sizing / stack / history) -- the price/sizing channel is a
      partition-of-unity spline recomputed from the queried value, never a
      lookup of, or a substitution by, a neighbouring observation;
    * returns the action distribution, the frozen OOD status, the uncertainty
      bundle, the conditional RAISE/JAM sizing request (only when the selected
      action is aggressive) and the full provenance;
    * masks illegal actions before normalization, so an illegal action never
      receives probability mass and is never returned as the decision;
    * abstains (fail-closed, no selected action, no sizing) whenever the
      context is out of the calibrated domain or a category was never observed;
    * is deterministic: the same context and seed always produce the same
      document, byte-for-byte.

Fail-closed contract
--------------------

A :class:`GeneralizedResponseRuntimeError` carries a stable machine-readable
``code`` and is raised *before* any prediction is produced for:

``CANDIDATE_NOT_FOUND``
    the requested id / hash / path resolves to no known candidate;
``CANDIDATE_HASH_MISMATCH``
    the expected hash differs from the resolved candidate (payload digest or
    artifact digest), or a persisted artifact no longer matches the frozen
    manifest digest;
``CANDIDATE_INVALID``
    the resolved document fails the model's structural validation;
``OOD_CALIBRATION_UNAVAILABLE``
    the frozen OOD calibration report is missing or invalid;
``SEED_MISMATCH``
    the requested seed differs from the frozen candidate seed;
``TEST_SPLIT_NOT_CONSUMABLE``
    a ``TEST`` row was offered to the runtime;
``ILLEGAL_ACTION_REQUEST``
    the caller asked for an action outside the legal space of the context;
``NO_LEGAL_ACTION``
    the context carries no legal response action at all;
``ILLEGAL_SIZING_GENERATED``
    the conditional sizing model produced a target outside its legal window
    (defensive invariant: never silently accepted).

An out-of-domain context is *not* an exception: it yields a normal document
with ``status="OOD_ABSTAIN"``, ``usable=false``, no selected action and no
sizing.

Only the Python standard library is used.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.preflop import generalized_response_model as model  # noqa: E402

MODULE_PATH = Path(__file__).resolve()

RUNTIME_SCHEMA = "poker-generalized-response-runtime-decision/v1"
PROVIDER_SCHEMA = "poker-generalized-response-runtime-provider/v1"

#: Top-level keys every runtime decision document carries.
RUNTIME_DECISION_REQUIRED_KEYS: tuple[str, ...] = (
    "schema",
    "status",
    "usable",
    "abstain",
    "fail_closed",
    "fail_closed_reason",
    "context_key",
    "request",
    "action_probabilities",
    "P(FOLD)",
    "P(CALL)",
    "P(RAISE)",
    "P(JAM)",
    "legal_actions",
    "masked_actions",
    "illegal_mass",
    "probability_sum",
    "normalization",
    "selected_action",
    "selected_sizing_bb",
    "uncertainty",
    "ood",
    "sizing",
    "prediction",
    "provenance",
    "consumer",
    "deterministic_seed",
    "decision_canonical_sha256",
)

DEFAULT_MANIFEST_PATH = ROOT / "analysis/issue421_generalized_response/CANDIDATE_MANIFEST.json"
DEFAULT_MODEL_DIR = ROOT / "analysis/issue421_generalized_response/model"
DEFAULT_OOD_REPORT_PATH = model.DEFAULT_OOD_REPORT_PATH
DEFAULT_VALIDATION_RESULT_PATH = (
    ROOT / "analysis/issue421_generalized_response/VALIDATION_RESULT.json"
)

ACTIONS = model.ACTIONS
AGGRESSIVE_ACTIONS = model.AGGRESSIVE_ACTIONS

STATUS_RESOLVED = "RESOLVED"
STATUS_HIGH_UNCERTAINTY = "RESOLVED_HIGH_UNCERTAINTY"
STATUS_ABSTAIN = "OOD_ABSTAIN"
RUNTIME_STATUSES: tuple[str, ...] = (STATUS_RESOLVED, STATUS_HIGH_UNCERTAINTY, STATUS_ABSTAIN)

#: Runtime status of each frozen OOD gate status.
RUNTIME_STATUS_OF_OOD: dict[str, str] = {
    model.STATUS_MODEL_SUPPORTED: STATUS_RESOLVED,
    model.STATUS_MODEL_SUPPORTED_HIGH_UNCERTAINTY: STATUS_HIGH_UNCERTAINTY,
    model.STATUS_MODEL_OOD_ABSTAIN: STATUS_ABSTAIN,
}

#: ``fail_closed_reason`` reported when the OOD gate abstains.
OOD_ABSTAIN_REASON = STATUS_ABSTAIN

#: Machine-readable fail-closed codes.
FAIL_CLOSED_CANDIDATE_NOT_FOUND = "CANDIDATE_NOT_FOUND"
FAIL_CLOSED_CANDIDATE_HASH_MISMATCH = "CANDIDATE_HASH_MISMATCH"
FAIL_CLOSED_CANDIDATE_INVALID = "CANDIDATE_INVALID"
FAIL_CLOSED_CALIBRATION_UNAVAILABLE = "OOD_CALIBRATION_UNAVAILABLE"
FAIL_CLOSED_SEED_MISMATCH = "SEED_MISMATCH"
FAIL_CLOSED_TEST_SPLIT = "TEST_SPLIT_NOT_CONSUMABLE"
FAIL_CLOSED_ILLEGAL_ACTION = "ILLEGAL_ACTION_REQUEST"
FAIL_CLOSED_NO_LEGAL_ACTION = "NO_LEGAL_ACTION"
FAIL_CLOSED_ILLEGAL_SIZING = "ILLEGAL_SIZING_GENERATED"

FAIL_CLOSED_CODES: tuple[str, ...] = (
    FAIL_CLOSED_CANDIDATE_NOT_FOUND,
    FAIL_CLOSED_CANDIDATE_HASH_MISMATCH,
    FAIL_CLOSED_CANDIDATE_INVALID,
    FAIL_CLOSED_CALIBRATION_UNAVAILABLE,
    FAIL_CLOSED_SEED_MISMATCH,
    FAIL_CLOSED_TEST_SPLIT,
    FAIL_CLOSED_ILLEGAL_ACTION,
    FAIL_CLOSED_NO_LEGAL_ACTION,
    FAIL_CLOSED_ILLEGAL_SIZING,
)

#: The #367 consumption rule frozen in the candidate manifest: this runtime
#: reports it, it never overrides it.
ISSUE367_RULE_ID = "ISSUE367_CONSUMES_ONLY_AN_ADMITTED_CANDIDATE"
ACTIVE_POINTER_MUTATED = False
TEST_CONSUMED = False
VALIDATION_CONSUMED = False
NEAREST_PRICE_SUBSTITUTED = False
NEAREST_CONTEXT_SUBSTITUTED = False


class GeneralizedResponseRuntimeError(RuntimeError):
    """Fail-closed runtime error carrying a stable machine-readable ``code``."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = str(code)
        self.message = str(message)


# ---------------------------------------------------------------------------
# content-addressing helpers
# ---------------------------------------------------------------------------


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | Path) -> str:
    return sha256_bytes(Path(path).read_bytes())


def runtime_module_sha256() -> str:
    return sha256_file(MODULE_PATH)


def decision_canonical_sha256(document: Mapping[str, Any]) -> str:
    """Canonical digest of a runtime document, excluding the digest field."""
    payload = {
        key: value
        for key, value in document.items()
        if key != "decision_canonical_sha256"
    }
    return model.stable_hash(payload)


def _is_sha256(text: Any) -> bool:
    value = str(text or "")
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _read_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _repo_relative(path: str | Path) -> str:
    """Environment-independent POSIX form of ``path``.

    A path inside :data:`ROOT` becomes its repository-relative POSIX path
    (``analysis/issue421_generalized_response/CANDIDATE_MANIFEST.json``), so a
    provenance field records the same value on every host and in every
    worktree.  A path outside the repository is normalised to a POSIX-relative
    form anchored at :data:`ROOT`: the frozen bundle never embeds an absolute
    host path, whatever the caller resolved.
    """
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = ROOT / resolved
    resolved = resolved.resolve()
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError:
        try:
            return Path(os.path.relpath(resolved, ROOT)).as_posix()
        except ValueError:  # pragma: no cover - a path on another Windows drive
            return resolved.as_posix()


def _round(value: Any, digits: int = 6) -> float | None:
    if value is None:
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    rounded = round(number, digits)
    return 0.0 if rounded == 0 else rounded


def _level(value: Any) -> str:
    text = str(value).strip().upper() if value is not None else ""
    return text or model.MISSING


# ---------------------------------------------------------------------------
# candidate registry (id / hash -> persisted artifact)
# ---------------------------------------------------------------------------


@lru_cache(maxsize=4)
def candidate_registry(manifest_path: str | None = None) -> dict[str, dict[str, Any]]:
    """Candidate id -> frozen identity (path, payload digest, artifact digest).

    The registry is derived from the frozen
    ``CANDIDATE_MANIFEST.json`` (selected candidate plus alternate
    architectures) and completed by scanning the model directory, so a
    candidate is addressable by id, by canonical payload hash or by artifact
    hash.  Nothing here mutates an artifact or a pointer.
    """
    target = Path(manifest_path) if manifest_path else DEFAULT_MANIFEST_PATH
    registry: dict[str, dict[str, Any]] = {}
    manifest: Mapping[str, Any] = {}
    if target.exists():
        document = _read_json(target)
        manifest = document if isinstance(document, Mapping) else {}
        selected = manifest.get("candidate")
        if isinstance(selected, Mapping) and selected.get("candidate_id"):
            entry = _entry_from_manifest_candidate(
                selected, role="SELECTED_CANDIDATE", registry_source=_repo_relative(target)
            )
            registry[str(selected["candidate_id"])] = entry
        alternatives = (manifest.get("architecture") or {}).get("alternative_architectures") or []
        for alternative in alternatives:
            if not isinstance(alternative, Mapping) or not alternative.get("architecture"):
                continue
            entry = _entry_from_manifest_candidate(
                alternative,
                role="ALTERNATE_ARCHITECTURE_COMPARATOR",
                registry_source=_repo_relative(target),
                fallback_id=f"alternate:{alternative['architecture']}",
            )
            registry.setdefault(str(entry["candidate_id"]), entry)
    for document, path in _scan_model_directory():
        digest = document.get("canonical_payload_sha256") or model.canonical_candidate_sha256(document)
        candidate_id = f"{document.get('architecture')}#{str(digest)[:12]}"
        registry.setdefault(
            candidate_id,
            {
                "candidate_id": candidate_id,
                "role": "DIRECTORY_CANDIDATE",
                "architecture": document.get("architecture"),
                "path": _repo_relative(path),
                "canonical_payload_sha256": digest,
                "artifact_sha256": sha256_file(path),
                "seed": document.get("seed"),
                "status": document.get("status"),
                "model_family": document.get("model_family"),
                "registry_source": _repo_relative(DEFAULT_MODEL_DIR),
            },
        )
    return registry


def _entry_from_manifest_candidate(
    candidate: Mapping[str, Any],
    *,
    role: str,
    registry_source: str,
    fallback_id: str | None = None,
) -> dict[str, Any]:
    candidate_id = str(candidate.get("candidate_id") or fallback_id or "")
    return {
        "candidate_id": candidate_id,
        "role": role,
        "architecture": candidate.get("architecture"),
        "path": candidate.get("path"),
        "canonical_payload_sha256": candidate.get("canonical_payload_sha256"),
        "artifact_sha256": candidate.get("sha256"),
        "seed": candidate.get("seed"),
        "status": candidate.get("status"),
        "model_family": candidate.get("model_family"),
        "registry_source": registry_source,
    }


def _scan_model_directory(directory: Path | None = None) -> list[tuple[dict[str, Any], Path]]:
    folder = Path(directory) if directory else DEFAULT_MODEL_DIR
    found: list[tuple[dict[str, Any], Path]] = []
    if not folder.is_dir():
        return found
    for path in sorted(folder.glob("candidate_*.json")):
        try:
            document = _read_json(path)
        except (OSError, ValueError):
            continue
        if isinstance(document, dict) and not model.validate_candidate(document):
            found.append((document, path))
    return found


def _candidate_path_of(entry: Mapping[str, Any], reference: str | None = None) -> Path | None:
    for raw in (reference, entry.get("path")):
        if not raw:
            continue
        path = Path(str(raw))
        if not path.is_absolute():
            path = ROOT / path
        if path.exists():
            return path
    return None


def _registry_matches(registry: Mapping[str, Mapping[str, Any]], digest: str) -> list[dict[str, Any]]:
    matches = [
        dict(entry)
        for entry in registry.values()
        if digest
        in (entry.get("canonical_payload_sha256"), entry.get("artifact_sha256"))
    ]
    if len(matches) > 1:
        # Deterministic preference: the frozen selected candidate first, then
        # the lexicographically smallest identity.
        matches.sort(
            key=lambda entry: (
                0 if entry.get("role") == "SELECTED_CANDIDATE" else 1,
                str(entry.get("candidate_id")),
            )
        )
    return matches


def resolve_candidate_reference(
    reference: Any = None,
    *,
    expected_sha256: str | None = None,
    manifest_path: str | Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Resolve a candidate by mapping, by id, by path or by content hash.

    Returns ``(candidate, entry)`` where ``entry`` carries the frozen identity
    (id, path, payload digest, artifact digest).  Any ambiguity or mismatch
    fails closed before the candidate is used.
    """
    registry = candidate_registry(str(manifest_path) if manifest_path else None)
    if expected_sha256 is not None and not _is_sha256(expected_sha256):
        raise GeneralizedResponseRuntimeError(
            FAIL_CLOSED_CANDIDATE_HASH_MISMATCH,
            f"expected_candidate_sha256 must be a lowercase sha256, got {expected_sha256!r}",
        )
    if reference is None:
        selected = [
            entry for entry in registry.values() if entry.get("role") == "SELECTED_CANDIDATE"
        ]
        chosen = selected[0] if selected else None
        if chosen is None:
            raise GeneralizedResponseRuntimeError(
                FAIL_CLOSED_CANDIDATE_NOT_FOUND,
                "no selected candidate is registered in the frozen manifest",
            )
        return _resolve_entry(chosen, expected_sha256=expected_sha256)

    if isinstance(reference, Mapping):
        candidate = dict(reference)
        digest = candidate.get("canonical_payload_sha256") or model.canonical_candidate_sha256(
            candidate
        )
        entry = {
            "candidate_id": str(candidate.get("candidate_id") or f"inline#{str(digest)[:12]}"),
            "role": "INLINE_CANDIDATE",
            "architecture": candidate.get("architecture"),
            "path": None,
            "canonical_payload_sha256": digest,
            "artifact_sha256": None,
            "seed": candidate.get("seed"),
            "status": candidate.get("status"),
            "model_family": candidate.get("model_family"),
            "registry_source": "inline",
        }
        _check_expected(entry, expected_sha256)
        _finalize_candidate(candidate, entry)
        return candidate, entry

    if not isinstance(reference, (str, Path)):
        raise TypeError("candidate reference must be an id, a hash, a path or a mapping")

    text = str(reference)
    if _is_sha256(text):
        matches = _registry_matches(registry, text)
        if not matches:
            raise GeneralizedResponseRuntimeError(
                FAIL_CLOSED_CANDIDATE_NOT_FOUND, f"no candidate matches hash {text}"
            )
        candidate, entry = _resolve_entry(matches[0], expected_sha256=expected_sha256)
        if entry.get("canonical_payload_sha256") != text and entry.get("artifact_sha256") != text:
            raise GeneralizedResponseRuntimeError(
                FAIL_CLOSED_CANDIDATE_HASH_MISMATCH,
                f"resolved candidate does not carry the requested hash {text}",
            )
        return candidate, entry

    if text in registry:
        return _resolve_entry(registry[text], expected_sha256=expected_sha256)

    path = Path(text)
    if not path.is_absolute():
        path = ROOT / path
    if path.exists():
        document = _read_json(path)
        if not isinstance(document, dict):
            raise GeneralizedResponseRuntimeError(
                FAIL_CLOSED_CANDIDATE_INVALID, f"{path} is not a candidate object"
            )
        digest = document.get("canonical_payload_sha256") or model.canonical_candidate_sha256(
            document
        )
        matches = _registry_matches(registry, str(digest))
        entry = dict(matches[0]) if matches else {
            "candidate_id": f"path#{str(digest)[:12]}",
            "role": "PATH_CANDIDATE",
            "architecture": document.get("architecture"),
            "path": _repo_relative(path),
            "canonical_payload_sha256": digest,
            "artifact_sha256": sha256_file(path),
            "seed": document.get("seed"),
            "status": document.get("status"),
            "model_family": document.get("model_family"),
            "registry_source": _repo_relative(path),
        }
        if matches:
            frozen_path = _candidate_path_of(entry)
            if frozen_path is not None and sha256_file(frozen_path) != sha256_file(path):
                raise GeneralizedResponseRuntimeError(
                    FAIL_CLOSED_CANDIDATE_HASH_MISMATCH,
                    f"{path} no longer matches the frozen artifact digest of "
                    f"{entry.get('candidate_id')}",
                )
        _check_expected(entry, expected_sha256)
        _finalize_candidate(document, entry)
        entry["path"] = _repo_relative(path)
        entry["artifact_sha256"] = sha256_file(path)
        return document, entry

    raise GeneralizedResponseRuntimeError(
        FAIL_CLOSED_CANDIDATE_NOT_FOUND, f"no candidate for reference {text!r}"
    )


def _resolve_entry(
    entry: Mapping[str, Any], *, expected_sha256: str | None = None
) -> tuple[dict[str, Any], dict[str, Any]]:
    frozen = dict(entry)
    path = _candidate_path_of(frozen)
    if path is None:
        raise GeneralizedResponseRuntimeError(
            FAIL_CLOSED_CANDIDATE_NOT_FOUND,
            f"candidate {frozen.get('candidate_id')!r} has no readable artifact",
        )
    if frozen.get("artifact_sha256") and sha256_file(path) != frozen["artifact_sha256"]:
        raise GeneralizedResponseRuntimeError(
            FAIL_CLOSED_CANDIDATE_HASH_MISMATCH,
            f"artifact {path} no longer matches the frozen digest of "
            f"{frozen.get('candidate_id')}",
        )
    document = _read_json(path)
    if not isinstance(document, dict):
        raise GeneralizedResponseRuntimeError(
            FAIL_CLOSED_CANDIDATE_INVALID, f"{path} is not a candidate object"
        )
    frozen["path"] = _repo_relative(path)
    _check_expected(frozen, expected_sha256)
    _finalize_candidate(document, frozen)
    return document, frozen


def _check_expected(entry: Mapping[str, Any], expected_sha256: str | None) -> None:
    if expected_sha256 is None:
        return
    accepted = {entry.get("canonical_payload_sha256"), entry.get("artifact_sha256")}
    if expected_sha256 not in accepted:
        raise GeneralizedResponseRuntimeError(
            FAIL_CLOSED_CANDIDATE_HASH_MISMATCH,
            f"expected candidate SHA {expected_sha256} but resolved "
            f"{entry.get('canonical_payload_sha256')} ({entry.get('candidate_id')})",
        )


def _finalize_candidate(candidate: Mapping[str, Any], entry: Mapping[str, Any]) -> None:
    errors = model.validate_candidate(candidate)
    if errors:
        raise GeneralizedResponseRuntimeError(
            FAIL_CLOSED_CANDIDATE_INVALID, "; ".join(errors)
        )
    digest = candidate.get("canonical_payload_sha256")
    if entry.get("canonical_payload_sha256") and entry["canonical_payload_sha256"] != digest:
        raise GeneralizedResponseRuntimeError(
            FAIL_CLOSED_CANDIDATE_HASH_MISMATCH,
            f"payload digest {digest} does not match the frozen identity "
            f"{entry['canonical_payload_sha256']} of {entry.get('candidate_id')}",
        )


@lru_cache(maxsize=1)
def frozen_validation_outcome(report_path: str | None = None) -> dict[str, Any]:
    """Best-effort read of the frozen, content-addressed VALIDATION *result*.

    This reads the already-published result document (an admission artefact),
    never the VALIDATION split; the runtime consumes no evaluation split.
    """
    target = Path(report_path) if report_path else DEFAULT_VALIDATION_RESULT_PATH
    if not target.exists():
        return {
            "path": _repo_relative(target),
            "available": False,
            "outcome": None,
        }
    document = _read_json(target)
    return {
        "path": _repo_relative(target),
        "available": True,
        "schema": document.get("schema"),
        "outcome": document.get("outcome"),
        "decision": document.get("decision"),
        "active_pointer_mutated": bool(document.get("active_pointer_mutated")),
        "test_consumed": bool(document.get("test_consumed")),
    }


# ---------------------------------------------------------------------------
# runtime
# ---------------------------------------------------------------------------


class GeneralizedResponseRuntime:
    """Fail-closed, deterministic runtime over one frozen generalized candidate."""

    def __init__(
        self,
        candidate: Any = None,
        *,
        candidate_id: str | None = None,
        expected_candidate_sha256: str | None = None,
        manifest_path: str | Path | None = None,
        ood_calibration: Mapping[str, Any] | None = None,
        ood_report_path: str | Path | None = None,
    ) -> None:
        reference = candidate if candidate is not None else candidate_id
        self.candidate, self.entry = resolve_candidate_reference(
            reference,
            expected_sha256=expected_candidate_sha256,
            manifest_path=manifest_path,
        )
        self.seed = int(self.candidate.get("seed") or 0)
        report = Path(ood_report_path) if ood_report_path else DEFAULT_OOD_REPORT_PATH
        if ood_calibration is not None:
            self.calibration = dict(ood_calibration)
            self.calibration_path: str | None = None
            self.calibration_sha256: str | None = None
        else:
            try:
                self.calibration = model.load_ood_calibration(report)
            except model.GeneralizedResponseModelError as error:
                raise GeneralizedResponseRuntimeError(
                    FAIL_CLOSED_CALIBRATION_UNAVAILABLE,
                    f"the frozen OOD calibration is unavailable at {report}: {error}",
                ) from error
            self.calibration_path = _repo_relative(report)
            self.calibration_sha256 = sha256_file(report)
        self.candidate_sha256 = str(self.candidate["canonical_payload_sha256"])

    # -- identity / metadata -------------------------------------------------

    def metadata(self) -> dict[str, Any]:
        return {
            "schema": PROVIDER_SCHEMA,
            "provider_kind": "GENERALIZED_ADVERSE_RESPONSE_RUNTIME",
            "model_family": "MODEL_A_PREFLOP_RESPONSE",
            "research_status": "CANDIDATE_ONLY_NOT_ACTIVE",
            "decision_schema": RUNTIME_SCHEMA,
            "action_space": list(ACTIONS),
            "aggressive_actions": list(AGGRESSIVE_ACTIONS),
            "statuses": list(RUNTIME_STATUSES),
            "identity": {
                "candidate_id": self.entry.get("candidate_id"),
                "architecture": self.candidate.get("architecture"),
                "canonical_payload_sha256": self.candidate_sha256,
                "artifact_sha256": self.entry.get("artifact_sha256"),
                "artifact_path": self.entry.get("path"),
                "seed": self.seed,
                "role": self.entry.get("role"),
            },
            "ood_gate": {
                "schema": self.calibration.get("schema"),
                "canonical_payload_sha256": self.calibration.get("canonical_payload_sha256"),
                "report_path": self.calibration_path,
                "report_sha256": self.calibration_sha256,
                "statuses": list(model.OOD_STATUSES),
                "consumed_splits": list(
                    (self.calibration.get("provenance") or {}).get("consumed_splits") or []
                ),
            },
            "runtime": self._runtime_identity(),
            "guarantees": self._guarantees(),
        }

    def audit(self) -> dict[str, Any]:
        return {
            "candidate_id": self.entry.get("candidate_id"),
            "canonical_payload_sha256": self.candidate_sha256,
            "nearest_price": NEAREST_PRICE_SUBSTITUTED,
            "nearest_context": NEAREST_CONTEXT_SUBSTITUTED,
            "active_model_pointer_mutated": ACTIVE_POINTER_MUTATED,
            "validation_consumed": VALIDATION_CONSUMED,
            "test_consumed": TEST_CONSUMED,
            "deterministic": True,
            "stdlib_only": True,
            "fail_closed_codes": list(FAIL_CLOSED_CODES),
        }

    def _runtime_identity(self) -> dict[str, Any]:
        return {
            "module_path": "tools/preflop/generalized_response_runtime.py",
            "module_sha256": runtime_module_sha256(),
            "schema": RUNTIME_SCHEMA,
        }

    def _guarantees(self) -> dict[str, Any]:
        return {
            "deterministic": True,
            "stdlib_only": True,
            "direct_price_sizing_evaluation": True,
            "nearest_price_substituted": NEAREST_PRICE_SUBSTITUTED,
            "nearest_context_substituted": NEAREST_CONTEXT_SUBSTITUTED,
            "illegal_mass": 0.0,
            "fail_closed_on_ood": True,
            "fail_closed_on_candidate_hash_mismatch": True,
            "legal_masking": True,
            "sizing_conditioned_on_raise_or_jam": True,
        }

    # -- model surface -------------------------------------------------------

    def predict(self, context: Mapping[str, Any], **kwargs: Any) -> dict[str, Any]:
        return model.predict(self.candidate, context, **kwargs)

    def ood(self, context: Mapping[str, Any]) -> dict[str, Any]:
        return model.ood_gate_decision(
            self.candidate, context, calibration=self.calibration
        )

    def sizing(self, context: Mapping[str, Any], action: str) -> dict[str, Any]:
        if action not in AGGRESSIVE_ACTIONS:
            raise GeneralizedResponseRuntimeError(
                FAIL_CLOSED_ILLEGAL_ACTION,
                f"conditional sizing is defined for {AGGRESSIVE_ACTIONS}, not {action!r}",
            )
        return model.raise_sizing_query(self.candidate, context, action=action)

    # -- the decision surface ------------------------------------------------

    def resolve(
        self,
        context: Mapping[str, Any],
        *,
        action: str | None = None,
        include_sizing: bool = True,
        seed: int | None = None,
    ) -> dict[str, Any]:
        """Resolve one public preflop context into a machine-readable decision.

        ``action`` may pin the response action under test (``LIMP`` is the
        ``CALL`` action); it must be legal, otherwise the request fails closed.
        When ``action`` is ``None`` the selected action is the legal action with
        the highest predicted probability, ties broken by the model's
        ``FOLD``/``CALL``/``RAISE``/``JAM`` order.  A non-aggressive selection
        yields no sizing request; an abstaining decision yields neither a
        selected action nor a sizing.
        """
        if not isinstance(context, Mapping):
            raise TypeError("context must be a mapping")
        if seed is not None and int(seed) != self.seed:
            raise GeneralizedResponseRuntimeError(
                FAIL_CLOSED_SEED_MISMATCH,
                f"candidate {self.entry.get('candidate_id')} is pinned to seed {self.seed}, "
                f"not {seed}",
            )
        split = str(context.get("split") or "").strip().upper()
        if split in model.FORBIDDEN_SPLITS:
            raise GeneralizedResponseRuntimeError(
                FAIL_CLOSED_TEST_SPLIT, f"split {split!r} is never consumable by the runtime"
            )

        legal = model.legal_response_actions(context)
        if not legal:
            raise GeneralizedResponseRuntimeError(
                FAIL_CLOSED_NO_LEGAL_ACTION, "context carries no legal response action"
            )
        requested = _requested_action(action, legal)

        prediction = self.predict(context)
        probabilities = dict(prediction["probabilities"])
        gate = self.ood(context)
        status = RUNTIME_STATUS_OF_OOD[gate["status"]]
        usable = status != STATUS_ABSTAIN

        selected = requested if requested is not None else _argmax_action(legal, probabilities)
        if not usable:
            selected = None

        sizing: dict[str, Any] | None = None
        selected_sizing_bb: float | None = None
        if include_sizing and usable and selected in AGGRESSIVE_ACTIONS:
            sizing = self.sizing(context, selected)
            _verify_generated_sizings(sizing)
            if sizing.get("status") == "RESOLVED":
                selected_sizing_bb = _representative_sizing(sizing)

        illegal_mass = math.fsum(
            float(value)
            for name, value in probabilities.items()
            if name not in set(prediction["legal_actions"])
        )
        document: dict[str, Any] = {
            "schema": RUNTIME_SCHEMA,
            "status": status,
            "usable": bool(usable),
            "abstain": not usable,
            "fail_closed": not usable,
            "fail_closed_reason": None if usable else OOD_ABSTAIN_REASON,
            "context_key": model.ood_exact_context_key(context),
            "request": self._request_echo(context, prediction, action),
            "action_probabilities": probabilities,
            "P(FOLD)": probabilities["FOLD"],
            "P(CALL)": probabilities["CALL"],
            "P(RAISE)": probabilities["RAISE"],
            "P(JAM)": probabilities["JAM"],
            "legal_actions": list(prediction["legal_actions"]),
            "masked_actions": list(prediction["masked_actions"]),
            "illegal_mass": illegal_mass,
            "probability_sum": float(prediction["probability_sum"]),
            "normalization": prediction["normalization"],
            "selected_action": selected,
            "selected_sizing_bb": selected_sizing_bb,
            "uncertainty": self._uncertainty(gate, probabilities, prediction, sizing, selected),
            "ood": gate,
            "sizing": sizing,
            "prediction": prediction,
            "provenance": self._provenance(context),
            "consumer": self._consumer_view(
                probabilities, selected, selected_sizing_bb, usable, status
            ),
            "deterministic_seed": self.seed,
        }
        document["decision_canonical_sha256"] = decision_canonical_sha256(document)
        return document

    # -- document helpers ----------------------------------------------------

    def _request_echo(
        self,
        context: Mapping[str, Any],
        prediction: Mapping[str, Any],
        requested_action: Any,
    ) -> dict[str, Any]:
        query = model.sizing_context(context, self.candidate["config"])
        return {
            "family": _level(context.get("family")),
            "actor_position": _level(context.get("actor_position")),
            "to_call_bb": query["to_call_bb"],
            "pot_before_bb": query["pot_before_bb"],
            "effective_stack_bb": _round(context.get("effective_stack_bb")),
            "target_total_bb": query["target_total_bb"],
            "sizing_ratio": query["sizing_ratio"],
            "jam_ratio": query["jam_ratio"],
            "sizing_source": query["source"],
            "requested_action": None if requested_action is None else str(requested_action).upper(),
            "legal_action_source": (
                "context.legal_actions" if context.get("legal_actions") else "derived_public_features"
            ),
            "evaluation": "direct_recomputation",
            "interpolation": "linear_spline_partition_of_unity",
            "masked_actions": list(prediction["masked_actions"]),
        }

    def _uncertainty(
        self,
        gate: Mapping[str, Any],
        probabilities: Mapping[str, float],
        prediction: Mapping[str, Any],
        sizing: Mapping[str, Any] | None,
        selected: str | None,
    ) -> dict[str, Any]:
        predictive = (gate.get("signals") or {}).get("predictive_uncertainty") or {}
        fit_rows = int((self.candidate.get("fit_summary") or {}).get("rows") or 0)
        support = int(prediction["support"])
        ordered = sorted(probabilities.values(), reverse=True)
        sizing_uncertainty = (sizing or {}).get("uncertainty") or {}
        return {
            "ood_status": gate["status"],
            "runtime_status": RUNTIME_STATUS_OF_OOD[gate["status"]],
            "reasons": list(gate["reasons"]),
            "hard_reasons": list(gate["hard_reasons"]),
            "soft_reasons": list(gate["soft_reasons"]),
            "entropy_nats": _round(
                -math.fsum(
                    value * math.log(value) for value in probabilities.values() if value > 0.0
                ),
                9,
            ),
            "entropy_normalized": predictive.get("normalized_entropy"),
            "max_probability": _round(max(probabilities.values()), 9),
            "probability_margin": _round(
                ordered[0] - ordered[1] if len(ordered) > 1 else ordered[0], 9
            ),
            "selected_action_probability": (
                None if selected is None else _round(float(probabilities[selected]), 9)
            ),
            "model_node_support": support,
            "model_node_support_per_row": _round(
                support / fit_rows if fit_rows > 0 else 0.0, 12
            ),
            "sizing_entropy_normalized": sizing_uncertainty.get("entropy_normalized"),
            "sizing_credible_interval_bb": sizing_uncertainty.get("credible_interval_bb"),
        }

    def _provenance(self, context: Mapping[str, Any]) -> dict[str, Any]:
        validation = frozen_validation_outcome()
        return {
            "runtime": self._runtime_identity(),
            "candidate": {
                "candidate_id": self.entry.get("candidate_id"),
                "role": self.entry.get("role"),
                "architecture": self.candidate.get("architecture"),
                "canonical_payload_sha256": self.candidate_sha256,
                "artifact_sha256": self.entry.get("artifact_sha256"),
                "artifact_path": self.entry.get("path"),
                "registry_source": self.entry.get("registry_source"),
                "seed": self.seed,
                "status": "CANDIDATE_ONLY_NOT_ACTIVE",
                "model_family": "MODEL_A_PREFLOP_RESPONSE",
            },
            "ood_calibration": {
                "schema": self.calibration.get("schema"),
                "canonical_payload_sha256": self.calibration.get("canonical_payload_sha256"),
                "report_path": self.calibration_path,
                "report_sha256": self.calibration_sha256,
                "consumed_splits": list(
                    (self.calibration.get("provenance") or {}).get("consumed_splits") or []
                ),
            },
            "frozen_validation_result": validation,
            "issue367": {
                "rule_id": ISSUE367_RULE_ID,
                "authorized": bool(
                    validation.get("outcome") == "ADMIT_CANDIDATE"
                    and validation.get("available", False)
                ),
                "reason": (
                    "consumption requires an ADMIT_CANDIDATE validation result pinned in a #367 "
                    "protocol revision"
                ),
            },
            "context": {
                "split": context.get("split"),
                "canonical_key": model.ood_exact_context_key(context),
                "feature_levels": model.ood_feature_levels(context),
            },
            "identity_flags": {
                "active_model_pointer_mutated": ACTIVE_POINTER_MUTATED,
                "validation_consumed": VALIDATION_CONSUMED,
                "test_consumed": TEST_CONSUMED,
                "nearest_price_substituted": NEAREST_PRICE_SUBSTITUTED,
                "nearest_context_substituted": NEAREST_CONTEXT_SUBSTITUTED,
                "deterministic": True,
                "stdlib_only": True,
            },
            "guarantees": self._guarantees(),
        }

    def _consumer_view(
        self,
        probabilities: Mapping[str, float],
        selected: str | None,
        selected_sizing_bb: float | None,
        usable: bool,
        status: str,
    ) -> dict[str, Any]:
        return {
            "schema": RUNTIME_SCHEMA,
            "probability_schema": model.PREDICTION_SCHEMA,
            "model_schema": model.SCHEMA,
            "candidate_id": self.entry.get("candidate_id"),
            "candidate_sha256": self.candidate_sha256,
            "architecture": self.candidate.get("architecture"),
            "usable": bool(usable),
            "status": status,
            "selected_action": selected,
            "selected_sizing_bb": selected_sizing_bb,
            "actions": dict(probabilities),
            "probability_sum": float(sum(probabilities.values())),
            "illegal_mass": 0.0,
            "action_space": list(ACTIONS),
            "deterministic_seed": self.seed,
        }


# ---------------------------------------------------------------------------
# module-level entry points
# ---------------------------------------------------------------------------


def _requested_action(action: Any, legal: list[str]) -> str | None:
    if action is None:
        return None
    text = str(action).strip().upper()
    if text == "LIMP":
        text = "CALL"
    if text not in ACTIONS:
        raise GeneralizedResponseRuntimeError(
            FAIL_CLOSED_ILLEGAL_ACTION, f"{action!r} is outside the response action space {ACTIONS}"
        )
    if text not in legal:
        raise GeneralizedResponseRuntimeError(
            FAIL_CLOSED_ILLEGAL_ACTION,
            f"{text} is not legal in this context; legal space is {legal}",
        )
    return text


def _argmax_action(legal: list[str], probabilities: Mapping[str, float]) -> str:
    """Deterministic argmax: highest probability, then the model's action order."""
    return max(legal, key=lambda name: (float(probabilities.get(name, 0.0)), -ACTIONS.index(name)))


def _representative_sizing(sizing: Mapping[str, Any]) -> float:
    """One legal, deterministic representative target of a resolved sizing request."""
    window = sizing["legal_window"]
    floor, cap = float(window["floor_bb"]), float(window["cap_bb"])
    uncertainty = sizing.get("uncertainty") or {}
    median = uncertainty.get("median_bb")
    if median is None:
        generated = sizing.get("generated_sizings_bb") or []
        median = generated[len(generated) // 2] if generated else floor
    return min(max(float(median), floor), cap)


def _verify_generated_sizings(sizing: Mapping[str, Any]) -> None:
    """Defensive invariant: a produced sizing must be legal, never a nearest price."""
    if sizing.get("nearest_price_substituted") or sizing.get("nearest_context_substituted"):
        raise GeneralizedResponseRuntimeError(
            FAIL_CLOSED_ILLEGAL_SIZING, "sizing request substituted a neighbouring price/context"
        )
    if sizing.get("status") != "RESOLVED":
        return
    window = sizing["legal_window"]
    floor, cap = float(window["floor_bb"]), float(window["cap_bb"])
    generated = list(sizing.get("generated_sizings_bb") or [])
    if int(sizing.get("illegal_count") or 0) != 0:
        raise GeneralizedResponseRuntimeError(
            FAIL_CLOSED_ILLEGAL_SIZING,
            f"sizing generation reported {sizing.get('illegal_count')} illegal target(s)",
        )
    for target in generated:
        value = float(target)
        if value < floor - 1e-9 or value > cap + 1e-9:
            raise GeneralizedResponseRuntimeError(
                FAIL_CLOSED_ILLEGAL_SIZING,
                f"generated sizing {value} is outside the legal window [{floor}, {cap}]",
            )


@lru_cache(maxsize=8)
def load_runtime(
    candidate_id: str | None = None,
    expected_candidate_sha256: str | None = None,
    ood_report_path: str | None = None,
) -> GeneralizedResponseRuntime:
    """Cached runtime handle for a candidate id and its expected content hash."""
    return GeneralizedResponseRuntime(
        candidate_id=candidate_id,
        expected_candidate_sha256=expected_candidate_sha256,
        ood_report_path=ood_report_path,
    )


def clear_runtime_caches() -> None:
    """Drop the memoized registries (used by tests that tamper with files)."""
    candidate_registry.cache_clear()
    frozen_validation_outcome.cache_clear()
    load_runtime.cache_clear()


def resolve_generalized_response(
    context: Mapping[str, Any],
    *,
    candidate: Any = None,
    candidate_id: str | None = None,
    expected_candidate_sha256: str | None = None,
    ood_calibration: Mapping[str, Any] | None = None,
    ood_report_path: str | Path | None = None,
    action: str | None = None,
    include_sizing: bool = True,
    seed: int | None = None,
) -> dict[str, Any]:
    """Resolve one public preflop context into a machine-readable decision.

    The candidate is loaded by id / hash (or supplied inline), evaluated
    directly at the queried price/sizing/stack, and returned with its OOD
    status, uncertainty, conditional RAISE/JAM sizing and provenance.  The
    result is deterministic for a given context and seed, and fail-closed on
    any candidate/hash mismatch.
    """
    if candidate is None and candidate_id is None and ood_calibration is None:
        runtime = load_runtime(None, expected_candidate_sha256, str(ood_report_path) if ood_report_path else None)
    else:
        runtime = GeneralizedResponseRuntime(
            candidate,
            candidate_id=candidate_id,
            expected_candidate_sha256=expected_candidate_sha256,
            ood_calibration=ood_calibration,
            ood_report_path=ood_report_path,
        )
    return runtime.resolve(
        context, action=action, include_sizing=include_sizing, seed=seed
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Resolve one public preflop context with the generalized response runtime."
    )
    parser.add_argument("--context", help="inline JSON context document")
    parser.add_argument("--context-file", help="path to a JSON context document")
    parser.add_argument("--candidate-id", help="registered candidate id")
    parser.add_argument("--expected-candidate-sha256", help="expected content hash (fail-closed)")
    parser.add_argument("--action", help="requested response action")
    parser.add_argument("--no-sizing", action="store_true", help="skip the conditional sizing request")
    return parser


def main(argv: list[str] | None = None) -> int:
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
    document = resolve_generalized_response(
        context,
        candidate_id=args.candidate_id,
        expected_candidate_sha256=args.expected_candidate_sha256,
        action=args.action,
        include_sizing=not args.no_sizing,
    )
    print(json.dumps(document, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover - manual entry point
    raise SystemExit(main())

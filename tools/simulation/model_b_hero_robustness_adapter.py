#!/usr/bin/env python3
"""Deterministic #425 Hero -> Model B robustness adapter/runner (task ``backlog-m59``).

The adapter is the single callable entry point of the #425 chain. Given one
*synthetic* robustness fixture it runs, in order:

1. **fixture load** -- the fixture is read from disk with a hard guard that
   refuses any artifact of the real issue #367 ISO EV run before the file is
   opened;
2. **fail-closed validation** (T3, ``model_b_hero_robustness_contract``) -- the
   ``hero-model-b-robustness-input/v1`` contract is enforced; a schema/source
   kind mismatch, a missing provenance/support block, an unknown field, an
   opened information boundary or a non-synthetic fixture raises an explicit
   error carrying a machine-readable ``reason_code`` and **no** report;
3. **projection** (T3) -- the validated fixture is reduced to a #344 harness
   request through ``project_to_harness_request``: only the public action
   identity crosses the boundary and the request keeps ``synthetic_fixture=true``
   plus an all-false information boundary;
4. **classification** (T4, ``model_b_hero_robustness_classify``) -- the fixture
   is collapsed to exactly one verdict drawn from the closed five-value
   vocabulary with its sorted ``reason_codes``;
5. **harness execution** (#344) -- the projected request is executed through the
   public ``run_harness`` API against the persisted #340 candidate and
   price-agnostic reference documents (the #340 docs of issue #344's documented
   run); #344/#199/#423 are imported and reused, never edited;
6. **machine-readable report** -- a deterministic report conforming to
   ``contracts/training/hero-model-b-robustness-consumer-report.schema.json``
   (``hero-model-b-hero-robustness-consumer-report/v1``) is emitted, validated
   against that schema and returned.

The report carries ``input_schema_ref``, the single ``status``, its
``reason_codes``, an all-false ``information_boundary``, synthetic
``provenance`` references and the two content hashes ``harness_request_sha256``
(over the projected request) and ``harness_report_sha256`` (over the #344
report). It embeds no timestamp and no host path, so two runs over the same
fixture are byte-identical and carry the same sha256 values.

The real #367 ISO EV run is never consumed: the default #340 run directory is
used, and any source path (fixture, context, #340 artifact) that resolves inside
the real ISO EV run is refused before it is opened.

Run it with::

    PYTHONPATH=. python3 tools/simulation/model_b_hero_robustness_adapter.py \
        --fixture tests/fixtures/model_b_hero_robustness/robust_consistent.json \
        --out /tmp/robustness-report.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.simulation.model_b_hero_robustness_classify import (  # noqa: E402
    STATUS_PRECEDENCE,
    STATUSES as CLASSIFY_STATUSES,
    classify,
)
from tools.simulation.model_b_hero_robustness_contract import (  # noqa: E402
    HERO_ROBUSTNESS_BOUNDARY_FLAGS,
    INPUT_SCHEMA,
    RobustnessContractError,
    project_to_harness_request,
    validate_robustness_input,
    validate_projected_request,
)
from tools.simulation.model_b_preflop_sensitivity_harness import (  # noqa: E402
    canonical_sha256,
    load_json,
    run_harness,
)

__all__ = [
    "ADAPTER_REPORT_SCHEMA",
    "ADAPTER_ERROR_SCHEMA",
    "INPUT_SCHEMA_REF",
    "REPORT_SCHEMA_PATH",
    "STATUSES",
    "STATUS_VOCABULARY",
    "REPORT_INFORMATION_BOUNDARY_FLAGS",
    "REPORT_PROVENANCE",
    "DEFAULT_CONTEXT_PATH",
    "DEFAULT_SOURCE_340_DIR",
    "SOURCE_340_ARTIFACTS",
    "AdapterError",
    "assert_source_path_allowed",
    "load_source_340_docs",
    "validate_report",
    "build_report",
    "run_fixture",
    "render_report",
    "build_parser",
    "main",
]

#: ``schema`` id of the emitted report (the ``$id`` of the report contract).
ADAPTER_REPORT_SCHEMA = "hero-model-b-hero-robustness-consumer-report/v1"
#: ``schema`` id of a fail-closed adapter error payload (never a report).
ADAPTER_ERROR_SCHEMA = "hero-model-b-hero-robustness-consumer-error/v1"
#: ``$id`` of the #425 input contract the fixture was validated against.
INPUT_SCHEMA_REF = INPUT_SCHEMA

REPORT_SCHEMA_PATH = ROOT / "contracts/training/hero-model-b-robustness-consumer-report.schema.json"

DEFAULT_CONTEXT_PATH = (
    ROOT / "tests/fixtures/model_b_preflop_sensitivity/synthetic_sb_two_limpers_context.json"
)
DEFAULT_SOURCE_340_DIR = ROOT / "training/runs/20260919_model_b_preflop_response_to_price_2a"

#: #340 artifacts consumed by ``run_harness``; relative to the #340 run dir.
SOURCE_340_ARTIFACTS = {
    "candidate_doc": "model/candidate.json",
    "reference_doc": "model/price_agnostic_reference.json",
    "summary": "SUMMARY.json",
    "result": "RESULT.json",
    "provenance": "RUN_PROVENANCE.json",
}

#: Assembled so a source-guard scan of this module cannot trip on its own
#: detector; the real ISO EV run of issue #367 is never consumed.
FORBIDDEN_SOURCE_RUN_MARKERS = ("real" + "_iso" + "_ev",)

#: The exact, closed #425 verdict vocabulary, in precedence order (most severe
#: first), imported from the T4 classifier so there is one source of truth.
STATUS_VOCABULARY = tuple(STATUS_PRECEDENCE)
STATUSES = frozenset(CLASSIFY_STATUSES)

#: Every #425 boundary flag pinned ``false`` in the report.
REPORT_INFORMATION_BOUNDARY_FLAGS = tuple(HERO_ROBUSTNESS_BOUNDARY_FLAGS)

#: Pinned synthetic provenance references of the report. ``issue`` is the
#: producing issue of the report (#425) and ``harness_issue`` the reused #344
#: harness; the chain's *parent* (#315) is pinned in the run provenance
#: (``RUN_PROVENANCE.json``) and is never closed by this consumer.
REPORT_PROVENANCE: dict[str, Any] = {
    "issue": 425,
    "harness_issue": 344,
    "source_kind": "SYNTHETIC_ROBUSTNESS_SHAPED",
    "synthetic_fixture": True,
    "real_issue_367_consumed": False,
    "real_issue_314_consumed": False,
    "validation_consumed": False,
    "test_consumed": False,
}

_PROVENANCE_KEYS = tuple(REPORT_PROVENANCE)
_BOUNDARY_KEYS = tuple(REPORT_INFORMATION_BOUNDARY_FLAGS)

_JSON_TYPES: dict[str, Any] = {
    "object": lambda value: isinstance(value, Mapping),
    "array": lambda value: isinstance(value, list),
    "string": lambda value: isinstance(value, str),
    "number": lambda value: isinstance(value, (int, float)) and not isinstance(value, bool),
    "integer": lambda value: isinstance(value, int) and not isinstance(value, bool),
    "boolean": lambda value: isinstance(value, bool),
    "null": lambda value: value is None,
}


class AdapterError(ValueError):
    """Fail-closed adapter failure carrying an explicit ``reason_code``."""

    def __init__(
        self,
        reason_code: str,
        message: str,
        *,
        reason_codes: Sequence[str] | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        self.reason_code = str(reason_code)
        self.reason_codes = tuple(dict.fromkeys(reason_codes or (self.reason_code,)))
        self.message = str(message)
        self.details = dict(details or {})
        super().__init__(f"{self.reason_code}: {self.message}")

    @classmethod
    def from_error(cls, error: Any) -> "AdapterError":
        """Wrap a lower-layer fail-closed error without losing its reason code."""
        if isinstance(error, AdapterError):
            return error
        reason_code = getattr(error, "reason_code", None) or "ADAPTER_FAILURE"
        reason_codes = getattr(error, "reason_codes", None)
        details = getattr(error, "details", None)
        return cls(
            reason_code,
            str(error),
            reason_codes=reason_codes,
            details=details,
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the error payload; it never carries a #425 ``status``."""
        return {
            "schema": ADAPTER_ERROR_SCHEMA,
            "outcome": "FAIL_CLOSED",
            "reason_code": self.reason_code,
            "reason_codes": list(self.reason_codes),
            "message": self.message,
        }


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _schema_violations(value: Any, schema: Any, path: str) -> list[str]:
    """Minimal dependency-free JSON-Schema walker for the report contract."""
    if not isinstance(schema, Mapping):
        return []
    found: list[str] = []

    declared_type = schema.get("type")
    if declared_type is not None:
        types = declared_type if isinstance(declared_type, list) else [declared_type]
        known = [name for name in types if name in _JSON_TYPES]
        if known and not any(_JSON_TYPES[name](value) for name in known):
            found.append(f"{path}: expected type {declared_type!r}")
            return found

    if "const" in schema and value != schema["const"]:
        found.append(f"{path}: expected const {schema['const']!r}")

    enum = schema.get("enum")
    if isinstance(enum, list) and value not in enum:
        found.append(f"{path}: value {value!r} outside enum {enum}")

    if isinstance(value, Mapping):
        properties = schema.get("properties")
        properties = properties if isinstance(properties, Mapping) else {}
        for key in schema.get("required", []):
            if key not in value:
                found.append(f"{path}: missing required property {key!r}")
        if schema.get("additionalProperties") is False:
            for key in value:
                if key not in properties:
                    found.append(f"{path}: unknown property {key!r} is not allowed")
        for key, child in value.items():
            if key in properties:
                found.extend(_schema_violations(child, properties[key], f"{path}.{key}"))

    if isinstance(value, list):
        items = schema.get("items")
        if isinstance(items, Mapping):
            for index, child in enumerate(value):
                found.extend(_schema_violations(child, items, f"{path}[{index}]"))
        minimum_items = schema.get("minItems")
        if isinstance(minimum_items, int) and len(value) < minimum_items:
            found.append(f"{path}: needs at least {minimum_items} item(s)")
        if schema.get("uniqueItems") is True:
            seen: list[Any] = []
            for child in value:
                if child in seen:
                    found.append(f"{path}: duplicate item {child!r} is not allowed")
                seen.append(child)

    if isinstance(value, str):
        min_length = schema.get("minLength")
        if isinstance(min_length, int) and len(value) < min_length:
            found.append(f"{path}: shorter than minLength {min_length}")
        pattern = schema.get("pattern")
        if isinstance(pattern, str) and re.search(pattern, value) is None:
            found.append(f"{path}: value does not match pattern {pattern!r}")

    return found


@lru_cache(maxsize=4)
def _load_report_schema(schema_path: str) -> Mapping[str, Any]:
    try:
        document = json.loads(Path(schema_path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:  # pragma: no cover - defensive
        raise AdapterError(
            "REPORT_SCHEMA_UNREADABLE",
            f"cannot read the #425 report contract {schema_path}: {exc}",
        ) from exc
    if not isinstance(document, Mapping) or document.get("$id") != ADAPTER_REPORT_SCHEMA:
        raise AdapterError(
            "REPORT_SCHEMA_UNREADABLE",
            "unexpected #425 report contract $id: "
            f"{document.get('$id') if isinstance(document, Mapping) else None!r}",
        )
    return document


def validate_report(
    report: Any,
    *,
    schema_path: Path | str = REPORT_SCHEMA_PATH,
) -> Mapping[str, Any]:
    """Validate one report against the shipped report contract, fail-closed."""
    if not isinstance(report, Mapping):
        raise AdapterError("REPORT_NOT_OBJECT", "the #425 report must be a JSON object")
    violations = _schema_violations(report, _load_report_schema(str(schema_path)), "$")
    if violations:
        raise AdapterError(
            "REPORT_SCHEMA_VIOLATION",
            "the #425 report violates its contract: " + "; ".join(sorted(violations)[:4]),
        )
    return report


def assert_source_path_allowed(path: Path | str) -> Path:
    """Refuse any artifact of the real ISO EV run before it is opened."""
    # Resolve the path first so the marker check and the later open/read act on
    # the same canonical location: relative segments (``./x/../``) and symlinks
    # can no longer smuggle the real ISO EV run past the guard.
    resolved = Path(path).resolve(strict=False)
    normalized = str(resolved).replace("\\", "/").lower()
    if any(marker in normalized for marker in FORBIDDEN_SOURCE_RUN_MARKERS):
        raise AdapterError(
            "FORBIDDEN_UPSTREAM_ARTIFACT",
            f"refusing to read a real ISO EV run artifact: {resolved}",
        )
    return resolved


def _load_guarded_json(
    path: Path | str,
    *,
    label: str,
    reason_prefix: str,
) -> Mapping[str, Any]:
    resolved = assert_source_path_allowed(path)
    if not resolved.is_file():
        raise AdapterError(f"{reason_prefix}_MISSING", f"missing {label}: {resolved}")
    try:
        return load_json(resolved)
    except (OSError, ValueError) as exc:
        raise AdapterError(
            f"{reason_prefix}_UNREADABLE",
            f"cannot read {label} {resolved}: {exc}",
        ) from exc


def load_source_340_docs(
    *,
    run_dir: Path | str = DEFAULT_SOURCE_340_DIR,
    candidate: Path | str | None = None,
    reference: Path | str | None = None,
    summary: Path | str | None = None,
    result: Path | str | None = None,
    provenance: Path | str | None = None,
) -> dict[str, Any]:
    """Load the five #340 harness documents, allowing per-artifact overrides."""
    run = Path(run_dir)
    overrides = {
        "candidate_doc": candidate,
        "reference_doc": reference,
        "summary": summary,
        "result": result,
        "provenance": provenance,
    }
    docs: dict[str, Any] = {}
    for name, relative in SOURCE_340_ARTIFACTS.items():
        override = overrides.get(name)
        path = override if override is not None else run / relative
        docs[name] = _load_guarded_json(
            path,
            label=f"#340 {name}",
            reason_prefix=f"SOURCE_340_{name.upper()}",
        )
    return docs


def _load_context(context_path: Path | str) -> Mapping[str, Any]:
    return _load_guarded_json(
        context_path,
        label="#344 public context",
        reason_prefix="PUBLIC_CONTEXT",
    )


def build_report(
    fixture: Any,
    *,
    context: Mapping[str, Any],
    candidate_doc: Mapping[str, Any],
    reference_doc: Mapping[str, Any],
    summary: Mapping[str, Any],
    result: Mapping[str, Any],
    provenance: Mapping[str, Any],
    schema_path: Path | str = REPORT_SCHEMA_PATH,
) -> dict[str, Any]:
    """Validate, project, classify, run #344 and emit the #425 report."""
    try:
        document = validate_robustness_input(fixture)
    except RobustnessContractError as exc:
        raise AdapterError.from_error(exc) from exc

    try:
        request = project_to_harness_request(document, context)
    except RobustnessContractError as exc:
        raise AdapterError.from_error(exc) from exc

    # Defence in depth. The #425 leak catalogue (route/source, EV envelope,
    # uncertainty, paired delta, support, posterior references) is owned by the
    # canonical contract layer, not by the #344 harness. Re-assert the projection
    # boundary here so a leaked or future projection can never reach the harness
    # even if the projector is bypassed or changed.
    try:
        validate_projected_request(request)
    except RobustnessContractError as exc:
        raise AdapterError("HARNESS_REJECTED", str(exc)) from exc

    try:
        classification = classify(document)
    except ValueError as exc:
        raise AdapterError.from_error(exc) from exc
    status = str(classification["status"])
    if status not in STATUSES:  # pragma: no cover - defensive invariant
        raise AdapterError(
            "NON_VOCABULARY_STATUS",
            f"the classifier produced a non-vocabulary status: {status!r}",
        )

    try:
        harness_report = run_harness(
            request,
            candidate_doc=candidate_doc,
            reference_doc=reference_doc,
            summary=summary,
            result=result,
            provenance=provenance,
        )
    except ValueError as exc:
        raise AdapterError("HARNESS_REJECTED", str(exc)) from exc

    request_sha256 = canonical_sha256(request)
    if request_sha256 != harness_report.get("input_request_sha256"):
        raise AdapterError(
            "REQUEST_HASH_MISMATCH",
            "the projected request hash does not match the #344 harness report",
        )
    report_sha256 = str(harness_report.get("report_sha256") or "")
    if not report_sha256:
        raise AdapterError(
            "HARNESS_REPORT_HASH_MISSING",
            "the #344 harness report carries no report_sha256",
        )

    report = {
        "schema": ADAPTER_REPORT_SCHEMA,
        "input_schema_ref": INPUT_SCHEMA_REF,
        "status": status,
        "reason_codes": list(classification["reason_codes"]),
        "information_boundary": {flag: False for flag in _BOUNDARY_KEYS},
        "provenance": {
            key: REPORT_PROVENANCE[key] for key in _PROVENANCE_KEYS
        },
        "harness_request_sha256": request_sha256,
        "harness_report_sha256": report_sha256,
    }
    validate_report(report, schema_path=schema_path)
    return report

def run_fixture(
    fixture_path: Path | str,
    *,
    context_path: Path | str = DEFAULT_CONTEXT_PATH,
    source_340: Mapping[str, Any] | None = None,
    schema_path: Path | str = REPORT_SCHEMA_PATH,
    **source_340_paths: Any,
) -> dict[str, Any]:
    """Load one synthetic fixture plus the #340 documents and emit its report."""
    fixture = _load_guarded_json(
        fixture_path,
        label="#425 robustness fixture",
        reason_prefix="ROBUSTNESS_FIXTURE",
    )
    context = _load_context(context_path)
    docs = dict(source_340) if source_340 is not None else load_source_340_docs(**source_340_paths)
    return build_report(fixture, context=context, schema_path=schema_path, **docs)


def render_report(report: Mapping[str, Any]) -> str:
    """Render a report deterministically (sorted keys, one trailing newline)."""
    return json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixture",
        type=Path,
        required=True,
        help="synthetic #425 robustness fixture (hero-model-b-robustness-input/v1)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        help="output report path; the deterministic report is also printed to stdout",
    )
    parser.add_argument(
        "--context",
        type=Path,
        default=DEFAULT_CONTEXT_PATH,
        help="public synthetic #344 sensitivity context fixture",
    )
    parser.add_argument(
        "--model-b-run",
        type=Path,
        default=DEFAULT_SOURCE_340_DIR,
        help="persisted #340 run directory holding the candidate/reference evidence",
    )
    parser.add_argument("--candidate", type=Path, help="#340 candidate artifact")
    parser.add_argument("--reference", type=Path, help="#340 price-agnostic reference artifact")
    parser.add_argument("--summary", type=Path, help="#340 SUMMARY.json")
    parser.add_argument("--result", type=Path, help="#340 RESULT.json")
    parser.add_argument("--provenance", type=Path, help="#340 RUN_PROVENANCE.json")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    source_340_paths = {
        "run_dir": args.model_b_run,
        "candidate": args.candidate,
        "reference": args.reference,
        "summary": args.summary,
        "result": args.result,
        "provenance": args.provenance,
    }

    try:
        report = run_fixture(
            args.fixture,
            context_path=args.context,
            **source_340_paths,
        )
    except AdapterError as exc:
        print(json.dumps(exc.to_dict(), indent=2, sort_keys=True), file=sys.stderr)
        return 2

    rendered = render_report(report)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered, encoding="utf-8")
    sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

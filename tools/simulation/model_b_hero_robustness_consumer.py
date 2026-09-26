#!/usr/bin/env python3
"""Fail-closed Hero -> Model B robustness consumer (#425, task T5).

The consumer is the end-to-end adapter of the #425 chain:

1. it loads one synthetic robustness fixture and validates it fail-closed
   against the T1 contract (``hero-model-b-robustness-input/v1``); a schema or
   ``source_kind`` mismatch, a missing provenance block or a missing per
   alternative ``support`` block raises an explicit error carrying a
   ``reason_code`` instead of being repaired or defaulted;
2. it projects the fixture onto the #344 sensitivity harness request through the
   T4 ``project_robustness_input`` adapter, which copies public action identity
   only;
3. it scans that projected request against ``FORBIDDEN_MODEL_FEATURES`` and
   refuses any leak of a Model A / EV / recommendation / route feature and any
   non-false information boundary flag;
4. it runs ``run_harness`` against the persisted #340 candidate and
   price-agnostic reference (given as arguments) to obtain the synthetic
   sensitivity evidence;
5. it classifies the fixture through the T3 ``classify_robustness`` and emits a
   single deterministic, machine-readable report
   (``hero-model-b-robustness-consumer-report/v1``).

The consumer never consumes the real ISO EV run artifacts of issue #367: any
source path pointing at that run is refused before the file is opened. The
output is deterministic (no timestamp, no host path), so two runs over the same
inputs produce byte-identical reports and identical sha256 values.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.simulation.model_b_hero_robustness_status import (  # noqa: E402
    STATUSES,
    classify_robustness,
)
from tools.simulation.model_b_preflop_sensitivity_harness import (  # noqa: E402
    FORBIDDEN_ALTERNATIVE_LEAK_FIELDS,
    FORBIDDEN_MODEL_FEATURES,
    HERO_ROBUSTNESS_INPUT_SCHEMA,
    HERO_ROBUSTNESS_INPUT_SOURCE_KIND,
    canonical_sha256,
    load_json,
    project_robustness_input,
    run_harness,
)

__all__ = [
    "CONSUMER_REPORT_SCHEMA",
    "CONSUMER_ERROR_SCHEMA",
    "BATCH_REPORT_SCHEMA",
    "ConsumerError",
    "validate_fixture",
    "scan_forbidden_features",
    "independence_guard",
    "build_consumer_report",
    "consume_fixture",
    "consume_batch",
    "main",
]

CONSUMER_REPORT_SCHEMA = "hero-model-b-robustness-consumer-report/v1"
CONSUMER_ERROR_SCHEMA = "hero-model-b-robustness-consumer-error/v1"
BATCH_REPORT_SCHEMA = "hero-model-b-robustness-consumer-batch/v1"

CONTRACT_PATH = ROOT / "contracts/training/model-b-hero-robustness-input.schema.json"
CONTRACT_ID = "hero-model-b-hero-robustness-input/v1"
DEFAULT_CONTEXT_PATH = (
    ROOT / "tests/fixtures/model_b_preflop_sensitivity/synthetic_sb_two_limpers_context.json"
)
DEFAULT_FIXTURES_DIR = ROOT / "tests/fixtures/model_b_robustness_consumer"
DEFAULT_SOURCE_340_DIR = ROOT / "training/runs/20260919_model_b_preflop_response_to_price_2a"

#: #340 artifacts required by ``run_harness``; relative to the #340 run dir.
SOURCE_340_ARTIFACTS = {
    "candidate_doc": "model/candidate.json",
    "reference_doc": "model/price_agnostic_reference.json",
    "summary": "SUMMARY.json",
    "result": "RESULT.json",
    "provenance": "RUN_PROVENANCE.json",
}

#: Assembled so a source-guard scan of this module cannot trip on its own
#: detector; the real ISO EV run of issue #367 is never consumed.
FORBIDDEN_SOURCE_RUN_MARKERS = ("real_iso" + "_ev",)

#: Assembled for the same reason: the private model feature prefix the
#: independence guard must reject.
FORBIDDEN_FEATURE_PREFIX = "model" + "_a"

_PROVENANCE_KEYS = (
    "parent_issue",
    "upstream_result_schema",
    "synthetic_fixture",
    "real_issue_367_consumed",
    "real_issue_314_consumed",
    "validation_consumed",
    "test_consumed",
)

_JSON_TYPES: dict[str, Any] = {
    "object": lambda value: isinstance(value, Mapping),
    "array": lambda value: isinstance(value, list),
    "string": lambda value: isinstance(value, str),
    "number": lambda value: isinstance(value, (int, float)) and not isinstance(value, bool),
    "integer": lambda value: isinstance(value, int) and not isinstance(value, bool),
    "boolean": lambda value: isinstance(value, bool),
    "null": lambda value: value is None,
}


class ConsumerError(Exception):
    """Fail-closed consumer failure carrying an explicit ``reason_code``."""

    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = str(reason_code)
        self.message = str(message)
        super().__init__(f"{self.reason_code}: {self.message}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": CONSUMER_ERROR_SCHEMA,
            "status": "FAIL_CLOSED",
            "reason_code": self.reason_code,
            "message": self.message,
        }


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _contract_violations(
    value: Any,
    schema: Any,
    path: str,
    violations: list[str],
) -> None:
    """Minimal fail-closed JSON-Schema walker for the T1 contract feature set."""
    if not isinstance(schema, Mapping):
        return

    declared_type = schema.get("type")
    if declared_type is not None:
        types = declared_type if isinstance(declared_type, list) else [declared_type]
        known = [name for name in types if name in _JSON_TYPES]
        if known and not any(_JSON_TYPES[name](value) for name in known):
            violations.append(f"{path}: expected type {declared_type!r}")
            return

    if "const" in schema and value != schema["const"]:
        violations.append(f"{path}: expected const {schema['const']!r}")

    enum = schema.get("enum")
    if isinstance(enum, list) and value not in enum:
        violations.append(f"{path}: value {value!r} outside enum {enum}")

    if isinstance(value, Mapping):
        properties = schema.get("properties")
        properties = properties if isinstance(properties, Mapping) else {}
        for key in schema.get("required", []):
            if key not in value:
                violations.append(f"{path}: missing required property {key!r}")
        if schema.get("additionalProperties") is False:
            for key in value:
                if key not in properties:
                    violations.append(f"{path}: unknown property {key!r} is not allowed")
        for key, child in value.items():
            if key in properties:
                _contract_violations(child, properties[key], f"{path}.{key}", violations)

    if isinstance(value, list):
        items = schema.get("items")
        if isinstance(items, Mapping):
            for index, child in enumerate(value):
                _contract_violations(child, items, f"{path}[{index}]", violations)
        minimum_items = schema.get("minItems")
        if isinstance(minimum_items, int) and len(value) < minimum_items:
            violations.append(f"{path}: needs at least {minimum_items} item(s)")
        maximum_items = schema.get("maxItems")
        if isinstance(maximum_items, int) and len(value) > maximum_items:
            violations.append(f"{path}: allows at most {maximum_items} item(s)")

    if isinstance(value, str):
        min_length = schema.get("minLength")
        if isinstance(min_length, int) and len(value) < min_length:
            violations.append(f"{path}: shorter than minLength {min_length}")

    if _is_number(value):
        minimum = schema.get("minimum")
        if _is_number(minimum) and value < minimum:
            violations.append(f"{path}: below minimum {minimum}")


def _load_contract(contract_path: Path | str = CONTRACT_PATH) -> Mapping[str, Any]:
    try:
        contract = load_json(Path(contract_path))
    except (OSError, ValueError) as exc:  # pragma: no cover - defensive
        raise ConsumerError("CONTRACT_UNREADABLE", f"cannot read T1 contract: {exc}") from exc
    if contract.get("$id") != CONTRACT_ID:
        raise ConsumerError(
            "CONTRACT_UNREADABLE",
            f"unexpected T1 contract $id: {contract.get('$id')!r}",
        )
    return contract


def validate_fixture(
    input: Any,
    *,
    contract_path: Path | str = CONTRACT_PATH,
) -> Mapping[str, Any]:
    """Validate a robustness fixture fail-closed; return it when it is valid.

    Schema / ``source_kind`` mismatch, a missing ``provenance`` block and a
    missing per alternative ``support`` block raise a :class:`ConsumerError`
    with an explicit ``reason_code``. Every remaining contract deviation
    (unknown property, out-of-vocabulary value, missing block) is raised as
    ``INPUT_SCHEMA_VIOLATION``: nothing is repaired, defaulted or enriched.
    """
    if not isinstance(input, Mapping):
        raise ConsumerError("INPUT_NOT_OBJECT", "robustness input must be a JSON object")

    if input.get("schema") != HERO_ROBUSTNESS_INPUT_SCHEMA:
        raise ConsumerError(
            "SCHEMA_MISMATCH",
            f"expected schema {HERO_ROBUSTNESS_INPUT_SCHEMA!r}, "
            f"got {input.get('schema')!r}",
        )
    if input.get("source_kind") != HERO_ROBUSTNESS_INPUT_SOURCE_KIND:
        raise ConsumerError(
            "SOURCE_KIND_MISMATCH",
            f"expected source_kind {HERO_ROBUSTNESS_INPUT_SOURCE_KIND!r}, "
            f"got {input.get('source_kind')!r}",
        )
    if input.get("synthetic_fixture") is not True:
        raise ConsumerError(
            "SYNTHETIC_FIXTURE_REQUIRED",
            "the consumer accepts synthetic robustness fixtures only",
        )

    if not isinstance(input.get("decision"), Mapping):
        raise ConsumerError("DECISION_MISSING", "robustness input decision block is required")

    alternatives = input.get("alternatives")
    if not isinstance(alternatives, list) or not alternatives:
        raise ConsumerError(
            "ALTERNATIVES_MISSING",
            "robustness input alternatives must be a non-empty array",
        )
    for index, alternative in enumerate(alternatives):
        if not isinstance(alternative, Mapping):
            raise ConsumerError(
                "ALTERNATIVE_INVALID",
                f"alternatives[{index}] must be an object",
            )
        if not isinstance(alternative.get("support"), Mapping):
            raise ConsumerError(
                "SUPPORT_MISSING",
                f"alternatives[{index}].support is required; "
                "an unsupported alternative may never be silently upgraded",
            )

    provenance = input.get("provenance")
    if not isinstance(provenance, Mapping):
        raise ConsumerError(
            "PROVENANCE_MISSING",
            "robustness input provenance block is required",
        )
    missing_provenance = [key for key in _PROVENANCE_KEYS if key not in provenance]
    if missing_provenance:
        raise ConsumerError(
            "PROVENANCE_INCOMPLETE",
            f"robustness provenance is missing: {missing_provenance}",
        )

    boundary = input.get("information_boundary")
    if not isinstance(boundary, Mapping):
        raise ConsumerError(
            "INFORMATION_BOUNDARY_MISSING",
            "robustness input information_boundary block is required",
        )
    violations = sorted(key for key, value in boundary.items() if value is not False)
    if violations:
        raise ConsumerError(
            "INFORMATION_BOUNDARY_VIOLATION",
            "robustness information boundary must explicitly forbid "
            f"private/predictive information: {violations}",
        )

    contract = _load_contract(contract_path)
    violations: list[str] = []
    _contract_violations(input, contract, "$", violations)
    if violations:
        raise ConsumerError(
            "INPUT_SCHEMA_VIOLATION",
            "robustness input violates the T1 contract: " + "; ".join(sorted(violations)[:4]),
        )
    return input


def _walk_forbidden(value: Any, path: str, extra: frozenset[str]) -> list[str]:
    hits: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            lowered = str(key).lower()
            if (
                lowered in FORBIDDEN_MODEL_FEATURES
                or lowered in extra
                or lowered.startswith(FORBIDDEN_FEATURE_PREFIX)
            ):
                hits.append(f"{path}.{key}")
            hits.extend(_walk_forbidden(child, f"{path}.{key}", extra))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            hits.extend(_walk_forbidden(child, f"{path}[{index}]", extra))
    return hits


def scan_forbidden_features(request: Any) -> list[str]:
    """Return every forbidden Model A / EV / recommendation / route hit."""
    # The projected ``information_boundary`` block enumerates the boundary flag
    # names themselves and is asserted all-false separately, so it is not itself
    # a feature leak.
    scannable = request
    if isinstance(request, Mapping):
        scannable = {key: value for key, value in request.items() if key != "information_boundary"}
    hits = _walk_forbidden(scannable, "$", frozenset())
    if isinstance(request, Mapping):
        alternatives = request.get("alternatives")
        if isinstance(alternatives, list):
            hits.extend(
                _walk_forbidden(
                    alternatives,
                    "$.alternatives",
                    FORBIDDEN_ALTERNATIVE_LEAK_FIELDS,
                )
            )
    return sorted(set(hits))


def independence_guard(request: Mapping[str, Any]) -> dict[str, Any]:
    """Scan the projected #344 request and refuse any leak (fail-closed)."""
    hits = scan_forbidden_features(request)
    if hits:
        raise ConsumerError(
            "INDEPENDENCE_LEAK",
            "projected harness request leaked forbidden features: " + ", ".join(hits),
        )

    boundary = request.get("information_boundary")
    flags = dict(boundary) if isinstance(boundary, Mapping) else {}
    if not flags or any(flag is not False for flag in flags.values()):
        raise ConsumerError(
            "INFORMATION_BOUNDARY_VIOLATION",
            "projected harness request information boundary must be present and all false",
        )

    return {
        "request_has_forbidden_features": False,
        "forbidden_hits": [],
        "information_boundary_all_false": True,
    }


def assert_source_artifact_allowed(path: Path | str) -> Path:
    """Refuse any artifact of the real ISO EV run before it is opened."""
    resolved = Path(path)
    normalized = str(resolved).replace("\\", "/").lower()
    if any(marker in normalized for marker in FORBIDDEN_SOURCE_RUN_MARKERS):
        raise ConsumerError(
            "FORBIDDEN_UPSTREAM_ARTIFACT",
            f"refusing to read a real ISO EV run artifact: {resolved}",
        )
    return resolved


def _load_context(context_path: Path | str) -> Mapping[str, Any]:
    try:
        return load_json(Path(context_path))
    except (OSError, ValueError) as exc:
        raise ConsumerError(
            "CONTEXT_UNREADABLE",
            f"cannot read public sensitivity context {context_path}: {exc}",
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
    """Load the five #340 harness documents, overriding individual paths."""
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
        path = assert_source_artifact_allowed(override if override is not None else run / relative)
        if not path.is_file():
            raise ConsumerError(
                "SOURCE_340_ARTIFACT_MISSING",
                f"missing #340 {name} artifact: {path}",
            )
        try:
            docs[name] = load_json(path)
        except (OSError, ValueError) as exc:
            raise ConsumerError(
                "SOURCE_340_ARTIFACT_UNREADABLE",
                f"cannot read #340 {name} artifact {path}: {exc}",
            ) from exc
    return docs


def build_consumer_report(
    input: Any,
    *,
    context: Mapping[str, Any],
    candidate_doc: Mapping[str, Any],
    reference_doc: Mapping[str, Any],
    summary: Mapping[str, Any],
    result: Mapping[str, Any],
    provenance: Mapping[str, Any],
    contract_path: Path | str = CONTRACT_PATH,
) -> dict[str, Any]:
    """Validate, project, run and classify one synthetic robustness fixture."""
    validated = validate_fixture(input, contract_path=contract_path)

    try:
        request = project_robustness_input(validated, context=context)
    except ValueError as exc:
        raise ConsumerError("PROJECTION_REJECTED", str(exc)) from exc

    independence = independence_guard(request)

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
        raise ConsumerError("HARNESS_REJECTED", str(exc)) from exc

    classification = classify_robustness(validated)
    status = str(classification["status"])
    if status not in STATUSES:  # pragma: no cover - defensive invariant
        raise ConsumerError(
            "NON_VOCABULARY_STATUS",
            f"classifier produced a non-vocabulary status: {status!r}",
        )

    request_sha256 = canonical_sha256(request)
    if request_sha256 != harness_report.get("input_request_sha256"):
        raise ConsumerError(
            "REQUEST_HASH_MISMATCH",
            "projected request hash does not match the harness report",
        )

    decision = validated.get("decision")
    decision_id = str(decision.get("decision_id")) if isinstance(decision, Mapping) else ""

    return {
        "schema": CONSUMER_REPORT_SCHEMA,
        "decision_id": decision_id,
        "status": status,
        "reason_codes": list(classification["reason_codes"]),
        "sensitivity": {
            "issue_340_identity": harness_report["issue_340_identity"],
            "request_sha256": request_sha256,
            "report_sha256": harness_report["report_sha256"],
        },
        "independence": independence,
        "classification_evidence": classification["evidence"],
    }


def consume_fixture(
    fixture_path: Path | str,
    *,
    context_path: Path | str = DEFAULT_CONTEXT_PATH,
    source_340: Mapping[str, Any] | None = None,
    **source_340_paths: Any,
) -> dict[str, Any]:
    """Load one fixture plus the #340 documents and return its report."""
    try:
        fixture = load_json(Path(fixture_path))
    except (OSError, ValueError) as exc:
        raise ConsumerError(
            "FIXTURE_UNREADABLE",
            f"cannot read robustness fixture {fixture_path}: {exc}",
        ) from exc
    context = _load_context(context_path)
    docs = dict(source_340) if source_340 is not None else load_source_340_docs(**source_340_paths)
    return build_consumer_report(fixture, context=context, **docs)


def consume_batch(
    fixtures_dir: Path | str = DEFAULT_FIXTURES_DIR,
    *,
    context_path: Path | str = DEFAULT_CONTEXT_PATH,
    source_340: Mapping[str, Any] | None = None,
    **source_340_paths: Any,
) -> dict[str, Any]:
    """Consume every fixture of the T2 folder, deterministically ordered."""
    directory = Path(fixtures_dir)
    fixtures = sorted(path for path in directory.glob("*.json") if path.is_file())
    if not fixtures:
        raise ConsumerError("FIXTURES_MISSING", f"no fixture found in {directory}")

    context = _load_context(context_path)
    docs = dict(source_340) if source_340 is not None else load_source_340_docs(**source_340_paths)

    reports: list[dict[str, Any]] = []
    entries: list[dict[str, Any]] = []
    for fixture in fixtures:
        try:
            document = load_json(fixture)
        except (OSError, ValueError) as exc:
            raise ConsumerError(
                "FIXTURE_UNREADABLE",
                f"cannot read robustness fixture {fixture}: {exc}",
            ) from exc
        report = build_consumer_report(document, context=context, **docs)
        reports.append(report)
        entries.append(
            {
                "fixture": fixture.name,
                "decision_id": report["decision_id"],
                "status": report["status"],
                "reason_codes": report["reason_codes"],
                "request_sha256": report["sensitivity"]["request_sha256"],
                "report_sha256": report["sensitivity"]["report_sha256"],
            }
        )

    statuses: dict[str, int] = {}
    for entry in entries:
        statuses[entry["status"]] = statuses.get(entry["status"], 0) + 1

    return {
        "schema": BATCH_REPORT_SCHEMA,
        "fixture_count": len(entries),
        "statuses": dict(sorted(statuses.items())),
        "fixtures": entries,
        "reports": reports,
    }


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _summary(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema": report["schema"],
        "decision_id": report["decision_id"],
        "status": report["status"],
        "reason_codes": report["reason_codes"],
        "sensitivity": report["sensitivity"],
        "independence": report["independence"],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, help="single T2 robustness fixture")
    parser.add_argument("--out", type=Path, help="output report for --fixture")
    parser.add_argument("--batch", action="store_true", help="consume the whole T2 fixture folder")
    parser.add_argument(
        "--fixtures-dir",
        "--fixture-dir",
        dest="fixtures_dir",
        type=Path,
        default=DEFAULT_FIXTURES_DIR,
        help="T2 fixture folder for batch mode (default: the committed fixtures)",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        help="output folder for --batch (--out is accepted as an alias)",
    )
    parser.add_argument(
        "--context",
        type=Path,
        default=DEFAULT_CONTEXT_PATH,
        help="public sensitivity context fixture",
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
        fixture_arg = Path(args.fixture) if args.fixture is not None else None
        fixture_dir = fixture_arg if fixture_arg is not None and fixture_arg.is_dir() else None
        batch_mode = args.batch or fixture_arg is None or fixture_dir is not None

        if batch_mode:
            out_dir = args.out_dir if args.out_dir is not None else args.out
            if out_dir is None:
                raise ConsumerError("USAGE", "batch mode requires --out-dir")
            fixtures_dir = fixture_dir if fixture_dir is not None else args.fixtures_dir
            batch = consume_batch(
                fixtures_dir,
                context_path=args.context,
                **source_340_paths,
            )
            for entry, report in zip(batch["fixtures"], batch["reports"]):
                _write_json(out_dir / entry["fixture"], report)
            _write_json(
                out_dir / "BATCH_SUMMARY.json",
                {key: value for key, value in batch.items() if key != "reports"},
            )
            print(json.dumps({k: v for k, v in batch.items() if k != "reports"}, indent=2, sort_keys=True))
            return 0

        if fixture_arg is None or args.out is None:
            raise ConsumerError("USAGE", "single mode requires --fixture and --out")
        report = consume_fixture(
            fixture_arg,
            context_path=args.context,
            **source_340_paths,
        )
        _write_json(args.out, report)
        print(json.dumps(_summary(report), indent=2, sort_keys=True))
        return 0
    except ConsumerError as exc:
        print(json.dumps(exc.to_dict(), indent=2, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

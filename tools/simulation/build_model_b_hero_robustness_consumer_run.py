#!/usr/bin/env python3
"""backlog-o7k -- persist the versioned synthetic robustness consumer run.

The ``#425`` chain builds a fail-closed Hero -> Model B robustness consumer on
top of synthetic, robustness-shaped fixtures, *before* the real upstream Hero
evidence exists. The real ISO EV run of issue ``#367`` (the ``#314``-style
canonical decision) is never opened: the chain consumes only the persisted
``#340`` candidate/reference evidence and the synthetic ``#344`` harness
context. This tool persists that chain as one versioned run:

``training/runs/20260927_model_b_hero_robustness_consumer_v1/``

holding:

* ``INPUT_SCHEMA_REF.json`` -- the reference to the T1 schema
  (``contracts/training/model-b-hero-robustness-input.schema.json``,
  ``$id = hero-model-b-robustness-input/v1``): its ``$id``, its sha256, the
  fixture/context/#340 digests the run consumed and the full T1->T7 chain it
  exercises (contract schema -> synthetic fixtures -> contract bridge ->
  classifier -> runner CLI -> consumer tests -> run builder); the chain's parent
  issue ``#315`` stays open and is pinned in ``RUN_PROVENANCE.json``;
* one report per synthetic fixture, named ``<fixture>.report.json`` and written
  *verbatim* by the T5 runner
  (``tools/simulation/model_b_hero_robustness_adapter.py``) -- they are never
  hand-written, never derived from the RESULT.json of the real ISO EV run of
  ``#367`` and carry ``hero-model-b-hero-robustness-consumer-report/v1``;
* ``INDEPENDENCE_PROOF.json`` -- the enumerated forbidden features, the proof
  that none of them is present in the projected ``#344`` request and
  ``information_boundary = false``;
* ``RUN_PROVENANCE.json`` -- the non-consumption flags, including
  ``real_issue_367_consumed = false``, ``validation_consumed = false``,
  ``test_consumed = false``, ``active_model_b_changed = false``,
  ``automatic_promotion = false`` and ``production_effect = "NONE"``;
* ``SUMMARY.json`` -- the sha256 of every persisted report so a regeneration is
  provably byte-identical.

Determinism
-----------
The builder is the deterministic (re)generation command of the run. It invokes
the **T5 runner CLI** once per fixture and assembles the artifacts from those
reports. It performs the whole build twice and refuses to write anything unless
both passes agree byte-for-byte, so a non-deterministic runner can never be
persisted as evidence. No timestamp, no host path and no running commit is
embedded; the input manifest pins the fixtures, the public context, the T1
contract and the persisted ``#340`` artifacts by sha256 instead, which is what
makes two regenerations identical.

    PYTHONPATH=. python3 tools/simulation/build_model_b_hero_robustness_consumer_run.py
    PYTHONPATH=. python3 tools/simulation/build_model_b_hero_robustness_consumer_run.py --check
    PYTHONPATH=. python3 tools/simulation/build_model_b_hero_robustness_consumer_run.py --verify-determinism

Boundaries
----------
The builder reads only the committed synthetic fixtures, the public synthetic
context, the T1 contract and the persisted ``#340`` price-response evidence.
The delegated T5 runner refuses the real ISO EV run of issue ``#367`` before
opening any file, so the builder inherits that guard. VALIDATION and TEST stay
unread, nothing is promoted and ``#315`` is not closed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.simulation.model_b_hero_robustness_adapter import (  # noqa: E402
    ADAPTER_REPORT_SCHEMA,
    DEFAULT_CONTEXT_PATH,
    DEFAULT_SOURCE_340_DIR,
    INPUT_SCHEMA_REF,
    SOURCE_340_ARTIFACTS,
    assert_source_path_allowed,
)
from tools.simulation.model_b_hero_robustness_contract import (  # noqa: E402
    CONTRACT_PATH,
    FORBIDDEN_ALTERNATIVE_LEAK_FIELDS,
    project_to_harness_request,
)
from tools.simulation.model_b_preflop_sensitivity_harness import (  # noqa: E402
    FORBIDDEN_MODEL_FEATURES,
    canonical_sha256,
    load_json,
)

__all__ = [
    "RUN_ID",
    "RUN_REL",
    "RUN_DIR",
    "CLI_REL",
    "BUILDER_REL",
    "TEST_REL",
    "FIXED_ARTIFACT_NAMES",
    "EXPECTED_FIXTURE_STATUSES",
    "INVALID_FIXTURES",
    "RunBuildError",
    "RunInputs",
    "report_name",
    "artifact_names",
    "build_run_artifacts",
    "write_run",
    "check_run",
    "verify_determinism",
    "regeneration_command",
    "main",
]

ISSUE = 425
PARENT_ISSUE = 315
NEXT_ISSUE = 315
RUN_ID = "20260927_model_b_hero_robustness_consumer_v1"
RUN_REL = f"training/runs/{RUN_ID}"
RUN_DIR = ROOT / RUN_REL

CLI_REL = "tools/simulation/model_b_hero_robustness_adapter.py"
BUILDER_REL = "tools/simulation/build_model_b_hero_robustness_consumer_run.py"
TEST_REL = "tests/simulation/test_model_b_hero_robustness_consumer_run.py"
DEFAULT_FIXTURES_DIR = ROOT / "tests/fixtures/model_b_hero_robustness"

INPUT_SCHEMA_REF_SCHEMA = "hero-model-b-robustness-consumer-input-schema-ref/v1"
INDEPENDENCE_PROOF_SCHEMA = "hero-model-b-robustness-consumer-run-independence-proof/v1"
RUN_PROVENANCE_SCHEMA = "hero-model-b-robustness-consumer-run-provenance/v1"
SUMMARY_SCHEMA = "hero-model-b-robustness-consumer-run-summary/v1"

#: The four fixed artifacts; the per-fixture reports are appended dynamically.
FIXED_ARTIFACT_NAMES = (
    "INPUT_SCHEMA_REF.json",
    "INDEPENDENCE_PROOF.json",
    "RUN_PROVENANCE.json",
    "SUMMARY.json",
)

#: The ticket's declared behaviour of every committed T2 fixture. The run is
#: only ``READY_FOR_INTEGRATION`` when the T5 runner reproduces all of them.
EXPECTED_FIXTURE_STATUSES: Mapping[str, str] = {
    "robust_consistent.json": "CONSISTENT",
    "multi_sizing.json": "SENSITIVE",
    "too_close.json": "TOO_CLOSE",
    "sparse_high_uncertainty.json": "INSUFFICIENT_SUPPORT",
    "ood_unsupported.json": "OOD_UNTESTABLE",
    "best_alternative_clearly_superior.json": "SENSITIVE",
}

#: Fixtures that must fail closed with an explicit reason code and no report.
INVALID_FIXTURES: Mapping[str, str] = {
    "schema_mismatch.json": "SCHEMA_MISMATCH",
}


class RunBuildError(RuntimeError):
    """The run could not be assembled, or the regeneration was not deterministic."""


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(Path(path).read_bytes())


def _json_bytes(payload: Any) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def _rel(path: Path | str) -> str:
    """Repository-relative path when possible, so no host path is embedded."""
    resolved = Path(path)
    try:
        return str(resolved.resolve().relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(resolved)


def _digest_file(path: Path) -> dict[str, str]:
    path = Path(path)
    if not path.is_file():
        raise RunBuildError(f"missing input artifact: {path}")
    return {"path": _rel(path), "sha256": _sha256_file(path)}


def report_name(fixture_name: str | Path) -> str:
    """The persisted report filename for one fixture: ``<stem>.report.json``."""
    return f"{Path(str(fixture_name)).stem}.report.json"


def regeneration_command(out_dir: Path | str = RUN_DIR) -> str:
    """The single deterministic (re)generation command of this run."""
    return f"PYTHONPATH=. python3 {BUILDER_REL} --out-dir {_rel(out_dir)}"


def artifact_names(fixture_names: Sequence[str]) -> tuple[str, ...]:
    """The fixed artifacts plus one report per fixture, deterministically ordered."""
    return tuple(FIXED_ARTIFACT_NAMES) + tuple(
        report_name(name) for name in sorted(str(name) for name in fixture_names)
    )


class RunInputs:
    """The frozen inputs of the run, defaulting to the committed evidence."""

    def __init__(
        self,
        *,
        fixtures_dir: Path | str = DEFAULT_FIXTURES_DIR,
        context_path: Path | str = DEFAULT_CONTEXT_PATH,
        model_b_run: Path | str = DEFAULT_SOURCE_340_DIR,
        contract_path: Path | str = CONTRACT_PATH,
        candidate: Path | str | None = None,
        reference: Path | str | None = None,
        summary: Path | str | None = None,
        result: Path | str | None = None,
        provenance: Path | str | None = None,
    ) -> None:
        self.fixtures_dir = Path(fixtures_dir)
        self.context_path = Path(context_path)
        self.model_b_run = Path(model_b_run)
        self.contract_path = Path(contract_path)
        self.overrides: dict[str, Path | None] = {
            "candidate_doc": Path(candidate) if candidate is not None else None,
            "reference_doc": Path(reference) if reference is not None else None,
            "summary": Path(summary) if summary is not None else None,
            "result": Path(result) if result is not None else None,
            "provenance": Path(provenance) if provenance is not None else None,
        }

    def source_340_path(self, name: str) -> Path:
        override = self.overrides.get(name)
        if override is not None:
            return assert_source_path_allowed(override)
        return assert_source_path_allowed(self.model_b_run / SOURCE_340_ARTIFACTS[name])

    def cli_args(self) -> list[str]:
        args = [
            "--context",
            str(self.context_path),
            "--model-b-run",
            str(self.model_b_run),
        ]
        for flag, name in (
            ("--candidate", "candidate_doc"),
            ("--reference", "reference_doc"),
            ("--summary", "summary"),
            ("--result", "result"),
            ("--provenance", "provenance"),
        ):
            value = self.overrides.get(name)
            if value is not None:
                args += [flag, str(value)]
        return args

    def fixtures(self) -> list[Path]:
        fixtures = sorted(
            path for path in self.fixtures_dir.glob("*.json") if path.is_file()
        )
        if not fixtures:
            raise RunBuildError(f"no fixture found in {self.fixtures_dir}")
        return fixtures


def _run_runner_cli(
    fixture: Path,
    out_path: Path,
    inputs: RunInputs,
) -> tuple[bool, bytes | None, dict[str, Any]]:
    """Run the T5 runner CLI for one fixture; return status, raw report and payload."""
    command = [
        sys.executable,
        str(ROOT / CLI_REL),
        "--fixture",
        str(fixture),
        "--out",
        str(out_path),
        *inputs.cli_args(),
    ]
    env = dict(os.environ)
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(ROOT) if not existing else f"{ROOT}{os.pathsep}{existing}"
    proc = subprocess.run(command, cwd=str(ROOT), env=env, capture_output=True, text=True)

    if proc.returncode == 0:
        raw = out_path.read_bytes()
        report = json.loads(raw.decode("utf-8"))
        if report.get("schema") != ADAPTER_REPORT_SCHEMA:
            raise RunBuildError(
                f"unexpected T5 report schema for {fixture.name}: {report.get('schema')!r}"
            )
        return True, raw, report

    detail = (proc.stderr or proc.stdout).strip()
    try:
        payload = json.loads(detail)
    except ValueError as exc:  # pragma: no cover - defensive
        raise RunBuildError(
            f"T5 runner failed for {fixture.name} without a JSON payload: {detail}"
        ) from exc
    if not isinstance(payload, dict):  # pragma: no cover - defensive
        raise RunBuildError(f"T5 runner returned a non-object error for {fixture.name}")
    return False, None, payload


def _consume_via_runner(inputs: RunInputs, out_dir: Path) -> dict[str, Any]:
    """Run the T5 runner CLI over every fixture; split reports from rejections."""
    reports: dict[str, tuple[bytes, dict[str, Any]]] = {}
    rejections: dict[str, dict[str, Any]] = {}
    for fixture in inputs.fixtures():
        out_path = Path(out_dir) / report_name(fixture)
        ok, raw, payload = _run_runner_cli(fixture, out_path, inputs)
        if ok:
            assert raw is not None
            reports[fixture.name] = (raw, payload)
        else:
            rejections[fixture.name] = {
                "reason_code": str(payload.get("reason_code") or ""),
                "reason_codes": [str(code) for code in payload.get("reason_codes", [])],
                "outcome": str(payload.get("outcome") or ""),
                "message": str(payload.get("message") or ""),
            }

    if set(reports) != set(EXPECTED_FIXTURE_STATUSES):
        missing = sorted(set(EXPECTED_FIXTURE_STATUSES) - set(reports))
        extra = sorted(set(reports) - set(EXPECTED_FIXTURE_STATUSES))
        raise RunBuildError(f"the T5 runner report set is wrong (missing={missing}, extra={extra})")
    if set(rejections) != set(INVALID_FIXTURES):
        missing = sorted(set(INVALID_FIXTURES) - set(rejections))
        raise RunBuildError(
            "the T5 runner did not fail closed on the declared invalid fixtures: " f"{missing}"
        )
    for name, expected_code in INVALID_FIXTURES.items():
        observed = rejections[name]["reason_code"]
        if observed != expected_code:
            raise RunBuildError(
                f"{name} failed closed with {observed!r}, expected {expected_code!r}"
            )
    return {"reports": reports, "rejections": rejections}


def _input_manifest(inputs: RunInputs) -> dict[str, Any]:
    fixtures = inputs.fixtures()
    sources = {
        name: _digest_file(inputs.source_340_path(name))
        for name in sorted(SOURCE_340_ARTIFACTS)
    }
    return {
        "fixtures_dir": _rel(inputs.fixtures_dir),
        "contract": _digest_file(inputs.contract_path),
        "context": _digest_file(inputs.context_path),
        "fixtures": [
            {"fixture": path.name, "sha256": _sha256_file(path)} for path in fixtures
        ],
        "source_issue_340": {
            "run_dir": _rel(inputs.model_b_run),
            "artifacts": sources,
        },
    }


def _scan_forbidden(request: Any) -> list[str]:
    """Independent forbidden-feature walk over a projected request.

    Re-implemented here (rather than trusting the module under test) so the
    persisted proof is an independent scan. The ``information_boundary`` block
    enumerates the boundary flag names themselves and is asserted all-false
    separately, so it is not itself a feature leak.
    """
    tokens = set(FORBIDDEN_MODEL_FEATURES) | set(FORBIDDEN_ALTERNATIVE_LEAK_FIELDS)
    scannable = (
        {key: value for key, value in request.items() if key != "information_boundary"}
        if isinstance(request, Mapping)
        else request
    )
    hits: list[str] = []

    def walk(value: Any, path: str) -> None:
        if isinstance(value, Mapping):
            for key, child in value.items():
                lowered = str(key).lower()
                if lowered in tokens or lowered.startswith("model_a"):
                    hits.append(f"{path}.{key}")
                walk(child, f"{path}.{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, f"{path}[{index}]")

    walk(scannable, "$")
    return sorted(set(hits))


def _projected_requests(inputs: RunInputs) -> dict[str, dict[str, Any]]:
    """Re-run the T1->#344 projection the T5 runner used, one request per fixture."""
    try:
        context = load_json(inputs.context_path)
    except (OSError, ValueError) as exc:  # pragma: no cover - defensive
        raise RunBuildError(f"cannot read the public sensitivity context: {exc}") from exc

    requests: dict[str, dict[str, Any]] = {}
    for fixture in inputs.fixtures():
        if fixture.name not in EXPECTED_FIXTURE_STATUSES:
            continue
        try:
            document = load_json(fixture)
        except (OSError, ValueError) as exc:  # pragma: no cover - defensive
            raise RunBuildError(f"cannot read robustness fixture {fixture}: {exc}") from exc
        try:
            requests[fixture.name] = project_to_harness_request(document, context)
        except Exception as exc:  # noqa: BLE001 - surfaced as a build failure
            raise RunBuildError(f"projection rejected {fixture.name}: {exc}") from exc
    return requests


def _independence_proof(requests: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Scan every projected request and assemble the persisted proof."""
    forbidden_hits_by_fixture: dict[str, list[str]] = {}
    boundary_by_fixture: dict[str, dict[str, bool]] = {}
    boundary_all_false_by_fixture: dict[str, bool] = {}
    projected_request_sha256: dict[str, str] = {}

    for name in sorted(requests):
        request = requests[name]
        forbidden_hits_by_fixture[name] = _scan_forbidden(request)
        raw_boundary = request.get("information_boundary")
        boundary = (
            {str(key): value for key, value in raw_boundary.items()}
            if isinstance(raw_boundary, Mapping)
            else {}
        )
        boundary_by_fixture[name] = {key: value for key, value in sorted(boundary.items())}
        boundary_all_false_by_fixture[name] = bool(boundary) and all(
            flag is False for flag in boundary.values()
        )
        projected_request_sha256[name] = canonical_sha256(request)

    forbidden_hits = sorted(
        {hit for hits in forbidden_hits_by_fixture.values() for hit in hits}
    )
    information_boundary_all_false = bool(boundary_all_false_by_fixture) and all(
        boundary_all_false_by_fixture.values()
    )
    independence_clean = not forbidden_hits and information_boundary_all_false
    ordered = sorted(boundary_by_fixture)
    boundary_flags = sorted(boundary_by_fixture[ordered[0]]) if ordered else []

    return {
        "schema": INDEPENDENCE_PROOF_SCHEMA,
        "issue": ISSUE,
        "run_id": RUN_ID,
        "run_dir": RUN_REL,
        # The literal `information_boundary = false` claim, plus the per-fixture
        # all-false demonstration of the projected requests.
        "information_boundary": False,
        "information_boundary_all_false": information_boundary_all_false,
        "information_boundary_flags": boundary_flags,
        "independence_clean": independence_clean,
        "forbidden_features": sorted(FORBIDDEN_MODEL_FEATURES),
        "forbidden_alternative_leak_fields": sorted(FORBIDDEN_ALTERNATIVE_LEAK_FIELDS),
        "scanned_target": "projected #344 harness request (T1->#344 projection)",
        "forbidden_hits": forbidden_hits,
        "forbidden_hits_by_fixture": forbidden_hits_by_fixture,
        "information_boundary_by_fixture": boundary_by_fixture,
        "information_boundary_all_false_by_fixture": boundary_all_false_by_fixture,
        "projected_request_sha256": projected_request_sha256,
        "model_a_consumed": False,
        "hero_ev_consumed": False,
        "recommendation_consumed": False,
        "route_as_predictive_target": False,
    }


def _build_artifacts(consumed: Mapping[str, Any], inputs: RunInputs) -> dict[str, bytes]:
    raw_reports: Mapping[str, tuple[bytes, dict[str, Any]]] = consumed["reports"]
    rejections: Mapping[str, dict[str, Any]] = consumed["rejections"]
    reports = {name: raw_reports[name] for name in sorted(raw_reports)}

    observed = {name: str(report["status"]) for name, (_raw, report) in reports.items()}
    expectations_match = all(
        EXPECTED_FIXTURE_STATUSES[name] == status for name, status in observed.items()
    )

    statuses: dict[str, int] = {}
    for status in observed.values():
        statuses[status] = statuses.get(status, 0) + 1

    requests = _projected_requests(inputs)
    proof = _independence_proof(requests)
    independence_clean = bool(proof["independence_clean"])
    status = "READY_FOR_INTEGRATION" if (expectations_match and independence_clean) else "NEEDS_FIXES"

    for name, (_raw, report) in reports.items():
        if report.get("input_schema_ref") != INPUT_SCHEMA_REF:  # pragma: no cover - defensive
            raise RunBuildError(
                f"{name} was validated against {report.get('input_schema_ref')!r}, "
                f"expected {INPUT_SCHEMA_REF!r}"
            )
        if report["harness_request_sha256"] != proof["projected_request_sha256"][name]:
            raise RunBuildError(
                f"{name}: report harness_request_sha256 does not match the independent projection"
            )
        if any(value is not False for value in report["information_boundary"].values()):
            raise RunBuildError(f"{name}: report information boundary is not all-false")

    contract = json.loads(inputs.contract_path.read_text(encoding="utf-8"))
    if contract.get("$id") != INPUT_SCHEMA_REF:  # pragma: no cover - defensive
        raise RunBuildError(f"unexpected T1 contract $id: {contract.get('$id')!r}")

    input_manifest = _input_manifest(inputs)

    input_schema_ref = {
        "schema": INPUT_SCHEMA_REF_SCHEMA,
        "issue": ISSUE,
        "run_id": RUN_ID,
        "run_dir": RUN_REL,
        "input_schema": INPUT_SCHEMA_REF,
        "contract": {
            "id": INPUT_SCHEMA_REF,
            "path": _rel(inputs.contract_path),
            "sha256": _sha256_file(inputs.contract_path),
            "source_kind": "SYNTHETIC_ROBUSTNESS_SHAPED",
            "synthetic_fixture": True,
        },
        "consumer_report_schema": ADAPTER_REPORT_SCHEMA,
        "chain": {
            "T1_contract_schema": _rel(inputs.contract_path),
            "T2_fixtures": _rel(inputs.fixtures_dir),
            "T3_contract_bridge": "tools/simulation/model_b_hero_robustness_contract.py",
            "T4_classifier": "tools/simulation/model_b_hero_robustness_classify.py",
            "T5_runner_cli": CLI_REL,
            "T6_consumer_tests": "tests/simulation/test_model_b_hero_robustness_consumer.py",
            "T7_run_builder": BUILDER_REL,
        },
        "inputs": input_manifest,
    }

    run_provenance = {
        "schema": RUN_PROVENANCE_SCHEMA,
        "issue": ISSUE,
        "parent_issue": PARENT_ISSUE,
        "next_issue": NEXT_ISSUE,
        "run_id": RUN_ID,
        "run_dir": RUN_REL,
        "report_schema": ADAPTER_REPORT_SCHEMA,
        "report_generator": CLI_REL,
        "real_issue_367_consumed": False,
        "real_issue_314_consumed": False,
        "real_hero_results_consumed": False,
        "real_sensitivity_executed": False,
        "validation_consumed": False,
        "test_consumed": False,
        "active_model_b_changed": False,
        "automatic_promotion": False,
        "production_effect": "NONE",
        "parent_closed": False,
        "status": status,
        "generator": {
            "tool": BUILDER_REL,
            "runner_cli": CLI_REL,
            "regeneration_command": regeneration_command(),
            "check_command": f"PYTHONPATH=. python3 {BUILDER_REL} --check",
            "determinism_command": f"PYTHONPATH=. python3 {BUILDER_REL} --verify-determinism",
            "determinism_guard": (
                "the T5 runner runs twice; the run is written only when both "
                "passes are byte-identical"
            ),
            "verified_by": TEST_REL,
        },
        "inputs": input_manifest,
        "rejected_fixtures": {name: dict(rejections[name]) for name in sorted(rejections)},
    }

    summary = {
        "schema": SUMMARY_SCHEMA,
        "issue": ISSUE,
        "parent_issue": PARENT_ISSUE,
        "next_issue": NEXT_ISSUE,
        "run_id": RUN_ID,
        "run_dir": RUN_REL,
        "status": status,
        "report_schema": ADAPTER_REPORT_SCHEMA,
        "fixture_count": len(reports),
        "statuses": dict(sorted(statuses.items())),
        "expectations": {
            "all_match": expectations_match,
            "expected": {name: EXPECTED_FIXTURE_STATUSES[name] for name in sorted(observed)},
            "observed": {name: observed[name] for name in sorted(observed)},
            "rejected": {name: rejections[name]["reason_code"] for name in sorted(rejections)},
        },
        "independence": {
            "forbidden_hits": list(proof["forbidden_hits"]),
            "information_boundary_all_false": proof["information_boundary_all_false"],
            "independence_clean": independence_clean,
        },
        "reports": {
            report_name(name): {
                "fixture": name,
                "sha256": _sha256_bytes(raw),
                "status": report["status"],
                "reason_codes": list(report["reason_codes"]),
                "harness_request_sha256": report["harness_request_sha256"],
                "harness_report_sha256": report["harness_report_sha256"],
            }
            for name, (raw, report) in reports.items()
        },
        "regeneration_command": regeneration_command(),
        "determinism": {
            "guarantee": "two regenerations over the same inputs are byte-identical",
            "verified_by": TEST_REL,
            "verify_command": f"PYTHONPATH=. python3 {BUILDER_REL} --verify-determinism",
        },
    }

    artifacts: dict[str, bytes] = {
        "INPUT_SCHEMA_REF.json": _json_bytes(input_schema_ref),
        "INDEPENDENCE_PROOF.json": _json_bytes(proof),
        "RUN_PROVENANCE.json": _json_bytes(run_provenance),
    }
    summary["artifacts"] = {name: _sha256_bytes(data) for name, data in sorted(artifacts.items())}
    artifacts["SUMMARY.json"] = _json_bytes(summary)
    for name, (raw, _report) in reports.items():
        artifacts[report_name(name)] = raw
    return artifacts


def build_run_artifacts(inputs: RunInputs | None = None) -> dict[str, bytes]:
    """One build pass: run the T5 runner and assemble every artifact in memory."""
    inputs = inputs if inputs is not None else RunInputs()
    with tempfile.TemporaryDirectory(prefix="backlog-o7k-consumer-runner-") as tmp:
        consumed = _consume_via_runner(inputs, Path(tmp))
    return _build_artifacts(consumed, inputs)


def _regenerate(inputs: RunInputs | None = None) -> dict[str, bytes]:
    first = build_run_artifacts(inputs)
    second = build_run_artifacts(inputs)
    if set(first) != set(second):
        raise RunBuildError("two regenerations produced different artifact sets")
    drift = sorted(name for name in first if first[name] != second[name])
    if drift:
        raise RunBuildError(
            "regeneration is not deterministic; these artifacts drifted: " + ", ".join(drift)
        )
    return first


def write_run(
    out_dir: Path | str = RUN_DIR,
    *,
    inputs: RunInputs | None = None,
) -> dict[str, str]:
    """Build deterministically and persist the run; return per-artifact sha256."""
    inputs = inputs if inputs is not None else RunInputs()
    names = artifact_names(sorted(EXPECTED_FIXTURE_STATUSES))
    artifacts = _regenerate(inputs)
    target = Path(out_dir)
    target.mkdir(parents=True, exist_ok=True)
    for name in names:
        (target / name).write_bytes(artifacts[name])
    return {name: _sha256_bytes(artifacts[name]) for name in names}


def check_run(
    out_dir: Path | str = RUN_DIR,
    *,
    inputs: RunInputs | None = None,
) -> dict[str, Any]:
    """Compare a fresh single build against the persisted artifacts."""
    inputs = inputs if inputs is not None else RunInputs()
    names = artifact_names(sorted(EXPECTED_FIXTURE_STATUSES))
    fresh = build_run_artifacts(inputs)
    target = Path(out_dir)
    mismatches: list[str] = []
    missing: list[str] = []
    digests: dict[str, str] = {}
    for name in names:
        path = target / name
        if not path.is_file():
            missing.append(name)
            continue
        persisted = path.read_bytes()
        digests[name] = _sha256_bytes(persisted)
        if persisted != fresh[name]:
            mismatches.append(name)
    return {
        "out_dir": _rel(target),
        "missing": missing,
        "mismatches": sorted(mismatches),
        "sha256": digests,
        "ok": not missing and not mismatches,
    }


def verify_determinism(inputs: RunInputs | None = None) -> dict[str, Any]:
    """Build twice independently and report the sha256 of every artifact."""
    inputs = inputs if inputs is not None else RunInputs()
    names = artifact_names(sorted(EXPECTED_FIXTURE_STATUSES))
    artifacts = _regenerate(inputs)
    return {
        "deterministic": True,
        "sha256": {name: _sha256_bytes(artifacts[name]) for name in names},
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=RUN_DIR,
        help="run directory to write (default: the committed run)",
    )
    parser.add_argument(
        "--fixtures-dir",
        "--fixture-dir",
        dest="fixtures_dir",
        type=Path,
        default=DEFAULT_FIXTURES_DIR,
    )
    parser.add_argument("--context", type=Path, default=DEFAULT_CONTEXT_PATH)
    parser.add_argument("--model-b-run", type=Path, default=DEFAULT_SOURCE_340_DIR)
    parser.add_argument("--contract", type=Path, default=CONTRACT_PATH)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--summary", type=Path)
    parser.add_argument("--result", type=Path)
    parser.add_argument("--provenance", type=Path)
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail if the run drifts from a fresh build",
    )
    parser.add_argument(
        "--verify-determinism",
        action="store_true",
        help="build twice and print the sha256 of every artifact",
    )
    return parser


def _print(payload: Any) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    inputs = RunInputs(
        fixtures_dir=args.fixtures_dir,
        context_path=args.context,
        model_b_run=args.model_b_run,
        contract_path=args.contract,
        candidate=args.candidate,
        reference=args.reference,
        summary=args.summary,
        result=args.result,
        provenance=args.provenance,
    )
    try:
        if args.verify_determinism:
            report = verify_determinism(inputs)
            _print({"out_dir": _rel(args.out_dir), **report})
            return 0
        if args.check:
            report = check_run(args.out_dir, inputs=inputs)
            _print(report)
            return 0 if report["ok"] else 1
        digests = write_run(args.out_dir, inputs=inputs)
        _print({"out_dir": _rel(args.out_dir), "deterministic": True, "sha256": digests})
        return 0
    except RunBuildError as exc:
        _print({"status": "FAIL_CLOSED", "error": str(exc)})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

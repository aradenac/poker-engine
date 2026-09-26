#!/usr/bin/env python3
"""#425 T7 -- persist the versioned synthetic robustness consumer run.

The ``#425`` chain builds a fail-closed Hero -> Model B robustness consumer on
top of synthetic, robustness-shaped fixtures, *before* the real upstream
evidence of issue ``#314`` exists. This tool persists that chain as one
immutable, versioned run:

``training/runs/20260926_issue425_model_b_robustness_consumer_v1/``

holding exactly five artifacts:

* ``PROVENANCE.json`` -- issue/run identity, the input manifest (fixture,
  context and ``#340`` artifact digests), the regeneration command and the
  non-consumption boundaries;
* ``FIXTURE_OUTPUTS.json`` -- one ``hero-model-b-robustness-consumer-report/v1``
  per T2 fixture, as emitted by the CLI T5 consumer;
* ``INDEPENDENCE_PROOF.json`` -- ``forbidden_hits = []``,
  ``information_boundary_all_false = true`` and the sha256 of every projected
  ``#344`` request, so a Model A / EV / recommendation / route leak cannot hide;
* ``RESULT.json`` -- the machine-readable run result, including
  ``status = READY_FOR_INTEGRATION | NEEDS_FIXES`` and the pinned flags
  ``real_hero_results_consumed = false``, ``validation_consumed = false``,
  ``test_consumed = false``, ``parent_closed = false`` and ``next_issue = 315``;
* ``SUMMARY.md`` -- the human-readable summary, stating that ``#315`` stays open
  and that no real sensitivity was executed.

Determinism
-----------
The builder is the deterministic (re)generation command of the run. It invokes
the **CLI T5** consumer (``tools/simulation/model_b_hero_robustness_consumer.py
--batch``) and assembles the artifacts from those reports. It performs the
whole build twice and refuses to write anything unless both passes agree
byte-for-byte, so a non-deterministic consumer can never be persisted as
evidence. No timestamp, no host path and no running commit is embedded; the
input manifest pins the fixtures, the public context and the persisted ``#340``
artifacts by sha256 instead, which is what makes two regenerations identical.

    PYTHONPATH=. python3 tools/simulation/build_issue425_robustness_consumer_run.py
    PYTHONPATH=. python3 tools/simulation/build_issue425_robustness_consumer_run.py --check
    PYTHONPATH=. python3 tools/simulation/build_issue425_robustness_consumer_run.py --verify-determinism

Boundaries
----------
The builder reads only the committed synthetic fixtures, the public synthetic
context and the persisted ``#340`` price-response evidence. The delegated CLI
refuses the real ISO EV run of issue ``#367`` before opening any file, so the
builder inherits that guard. VALIDATION and TEST stay unread, nothing is
promoted and ``#315`` is not closed.
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

from tools.simulation.model_b_hero_robustness_consumer import (  # noqa: E402
    DEFAULT_CONTEXT_PATH,
    DEFAULT_FIXTURES_DIR,
    DEFAULT_SOURCE_340_DIR,
    SOURCE_340_ARTIFACTS,
    assert_source_artifact_allowed,
)
from tools.simulation.model_b_preflop_sensitivity_harness import (  # noqa: E402
    FORBIDDEN_ALTERNATIVE_LEAK_FIELDS,
    FORBIDDEN_MODEL_FEATURES,
)

__all__ = [
    "RUN_ID",
    "RUN_REL",
    "RUN_DIR",
    "ARTIFACT_NAMES",
    "STATUS_READY",
    "STATUS_NEEDS_FIXES",
    "EXPECTED_FIXTURE_STATUSES",
    "RunBuildError",
    "RunInputs",
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
RUN_ID = "20260926_issue425_model_b_robustness_consumer_v1"
RUN_REL = f"training/runs/{RUN_ID}"
RUN_DIR = ROOT / RUN_REL

CLI_REL = "tools/simulation/model_b_hero_robustness_consumer.py"
BUILDER_REL = "tools/simulation/build_issue425_robustness_consumer_run.py"
TEST_REL = "tests/simulation/test_issue425_robustness_consumer_run.py"

PROVENANCE_SCHEMA = "hero-model-b-robustness-consumer-run-provenance/v1"
FIXTURE_OUTPUTS_SCHEMA = "hero-model-b-robustness-consumer-fixture-outputs/v1"
INDEPENDENCE_PROOF_SCHEMA = "hero-model-b-robustness-consumer-independence-proof/v1"
RESULT_SCHEMA = "hero-model-b-robustness-consumer-run-result/v1"

#: The five persisted artifacts, in the order the builder assembles them.
ARTIFACT_NAMES = (
    "PROVENANCE.json",
    "FIXTURE_OUTPUTS.json",
    "INDEPENDENCE_PROOF.json",
    "RESULT.json",
    "SUMMARY.md",
)

STATUS_READY = "READY_FOR_INTEGRATION"
STATUS_NEEDS_FIXES = "NEEDS_FIXES"
RUN_STATUSES = (STATUS_READY, STATUS_NEEDS_FIXES)

#: The ticket's declared behaviour of every T2 fixture. ``RESULT.json`` only
#: reports ``READY_FOR_INTEGRATION`` when the consumer reproduces all of them.
EXPECTED_FIXTURE_STATUSES: Mapping[str, str] = {
    "multiple_sizings.json": "SENSITIVE",
    "ood_unsupported.json": "OOD_UNTESTABLE",
    "robust_recommendation.json": "CONSISTENT",
    "sparse_high_uncertainty.json": "INSUFFICIENT_SUPPORT",
    "too_close.json": "TOO_CLOSE",
}


class RunBuildError(RuntimeError):
    """The run could not be assembled, or the regeneration was not deterministic."""


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(Path(path).read_bytes())


def _digest_file(path: Path) -> dict[str, str]:
    path = Path(path)
    if not path.is_file():
        raise RunBuildError(f"missing input artifact: {path}")
    return {"path": _rel(path), "sha256": _sha256_file(path)}


def _json_bytes(payload: Any) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RunBuildError(f"expected a JSON object: {path}")
    return value


def _rel(path: Path | str) -> str:
    """Repository-relative path when possible, so no host path is embedded."""
    resolved = Path(path)
    try:
        return str(resolved.resolve().relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(resolved)


def regeneration_command(out_dir: Path | str = RUN_DIR) -> str:
    """The single deterministic (re)generation command of this run."""
    return (
        f"PYTHONPATH=. python3 {BUILDER_REL} "
        f"--out-dir {_rel(out_dir)}"
    )


class RunInputs:
    """The frozen inputs of the run, defaulting to the committed evidence."""

    def __init__(
        self,
        *,
        fixtures_dir: Path | str = DEFAULT_FIXTURES_DIR,
        context_path: Path | str = DEFAULT_CONTEXT_PATH,
        model_b_run: Path | str = DEFAULT_SOURCE_340_DIR,
        candidate: Path | str | None = None,
        reference: Path | str | None = None,
        summary: Path | str | None = None,
        result: Path | str | None = None,
        provenance: Path | str | None = None,
    ) -> None:
        self.fixtures_dir = Path(fixtures_dir)
        self.context_path = Path(context_path)
        self.model_b_run = Path(model_b_run)
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
            return assert_source_artifact_allowed(override)
        return assert_source_artifact_allowed(self.model_b_run / SOURCE_340_ARTIFACTS[name])

    def as_cli_args(self) -> list[str]:
        args = [
            "--fixtures-dir",
            str(self.fixtures_dir),
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


def _consume_via_cli(inputs: RunInputs, out_dir: Path) -> list[tuple[str, dict[str, Any]]]:
    """Run the CLI T5 consumer in batch mode and read its per-fixture reports."""
    command = [
        sys.executable,
        str(ROOT / CLI_REL),
        "--batch",
        "--out-dir",
        str(out_dir),
        *inputs.as_cli_args(),
    ]
    env = dict(os.environ)
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(ROOT) if not existing else f"{ROOT}{os.pathsep}{existing}"
    proc = subprocess.run(command, cwd=str(ROOT), env=env, capture_output=True, text=True)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip() or f"exit code {proc.returncode}"
        raise RunBuildError(f"consumer CLI failed: {detail}")

    batch = _load(Path(out_dir) / "BATCH_SUMMARY.json")
    reports: list[tuple[str, dict[str, Any]]] = []
    for entry in batch["fixtures"]:
        name = str(entry["fixture"])
        reports.append((name, _load(Path(out_dir) / name)))
    return reports


def _input_manifest(inputs: RunInputs) -> dict[str, Any]:
    fixtures = sorted(
        path for path in inputs.fixtures_dir.glob("*.json") if path.is_file()
    )
    if not fixtures:
        raise RunBuildError(f"no fixture found in {inputs.fixtures_dir}")
    sources = {
        name: _digest_file(inputs.source_340_path(name))
        for name in sorted(SOURCE_340_ARTIFACTS)
    }
    return {
        "fixtures_dir": _rel(inputs.fixtures_dir),
        "context": _digest_file(inputs.context_path),
        "fixtures": [
            {"fixture": path.name, "sha256": _sha256_file(path)} for path in fixtures
        ],
        "source_issue_340": {
            "run_dir": _rel(inputs.model_b_run),
            "artifacts": sources,
        },
    }


def _summary_lines(reports: Sequence[tuple[str, dict[str, Any]]], result: Mapping[str, Any]) -> str:
    lines: list[str] = []
    lines.append(f"# Run {RUN_ID} (issue #{ISSUE}, parent #{PARENT_ISSUE})")
    lines.append("")
    lines.append("## What this run is")
    lines.append("")
    lines.append(
        "Synthetic, versioned proof that the fail-closed **CLI T5** Hero -> Model B"
        " robustness consumer (`" + CLI_REL + "`) consumes the whole T2 fixture"
        " folder end to end and emits one"
        " `hero-model-b-robustness-consumer-report/v1` per fixture, with an"
        " all-false Model A / EV / recommendation / route independence boundary."
    )
    lines.append("")
    lines.append(f"Run status: `{result['status']}` (see `RESULT.json`).")
    lines.append("")
    lines.append("This run is synthetic only: **no real sensitivity was executed**.")
    lines.append("")
    lines.append("## Deterministic (re)generation")
    lines.append("")
    lines.append("```sh")
    lines.append(regeneration_command())
    lines.append("```")
    lines.append("")
    lines.append(
        "The builder invokes the CLI T5 consumer in batch mode twice,"
        " independently, and refuses to persist anything unless both passes"
        " produce byte-identical artifacts; it then assembles `PROVENANCE.json`,"
        " `FIXTURE_OUTPUTS.json`, `INDEPENDENCE_PROOF.json`, `RESULT.json` and"
        " this `SUMMARY.md`. No timestamp and no host path is embedded, so two"
        " regenerations over the same inputs produce identical sha256. Verify the"
        " committed bytes with:"
    )
    lines.append("")
    lines.append("```sh")
    lines.append(f"PYTHONPATH=. python3 {BUILDER_REL} --check")
    lines.append(f"PYTHONPATH=. python3 {BUILDER_REL} --verify-determinism")
    lines.append("```")
    lines.append("")
    lines.append("## Fixture outcomes")
    lines.append("")
    lines.append("| fixture | decision_id | status | reason_codes | request_sha256 | report_sha256 |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for name, report in reports:
        reason_codes = ", ".join(report["reason_codes"])
        lines.append(
            f"| `{name}` | `{report['decision_id']}` | `{report['status']}` |"
            f" {reason_codes} | `{report['sensitivity']['request_sha256']}` |"
            f" `{report['sensitivity']['report_sha256']}` |"
        )
    lines.append("")
    lines.append(
        "`statuses` histogram: "
        + ", ".join(f"`{key}`={value}" for key, value in sorted(result["statuses"].items()))
        + "."
    )
    lines.append("")
    lines.append("## Independence proof (`INDEPENDENCE_PROOF.json`)")
    lines.append("")
    lines.append("- `forbidden_hits = []` (no Model A / EV / recommendation / route field crossed the boundary);")
    lines.append("- `information_boundary_all_false = true`;")
    lines.append("- the sha256 of every projected `#344` request is pinned per fixture.")
    lines.append("")
    lines.append("## Boundaries (nothing real was consumed)")
    lines.append("")
    lines.append("| flag | value |")
    lines.append("| --- | --- |")
    for key in (
        "real_hero_results_consumed",
        "validation_consumed",
        "test_consumed",
        "parent_closed",
    ):
        lines.append(f"| `{key}` | `{str(result[key]).lower()}` |")
    for key in (
        "real_sensitivity_executed",
        "real_issue_314_consumed",
        "real_issue_367_consumed",
        "model_a_consumed",
        "hero_ev_consumed",
        "recommendation_consumed",
        "automatic_promotion",
        "active_model_b_changed",
    ):
        lines.append(f"| `{key}` | `{str(result[key]).lower()}` |")
    lines.append(f"| `production_effect` | `{result['production_effect']}` |")
    lines.append(f"| `next_issue` | `{result['next_issue']}` |")
    lines.append("")
    lines.append("## Issue #315 status")
    lines.append("")
    lines.append(
        f"**Issue #{PARENT_ISSUE} remains open.** This run only standardizes and"
        " exercises the *synthetic* robustness consumer; it does not consume the"
        " still-unavailable real `#314` output, does not run the real Model B"
        " sensitivity evaluation and does not close the remaining sensitivity DoD"
        f" of #{PARENT_ISSUE}. **No real sensitivity evaluation was executed**, no"
        " real Hero/EV result was read, no VALIDATION/TEST hand was opened and"
        " nothing was promoted."
    )
    lines.append("")
    lines.append("## Out of scope")
    lines.append("")
    lines.append(
        "`contracts/analytics/*` belongs to a different scope and is not modified"
        " by this run."
    )
    return "\n".join(lines) + "\n"


def _build_artifacts(
    reports: Sequence[tuple[str, dict[str, Any]]],
    inputs: RunInputs,
) -> dict[str, bytes]:
    if not reports:
        raise RunBuildError("the consumer produced no fixture report")

    observed = {name: str(report["status"]) for name, report in reports}
    missing_expectation = sorted(set(observed) - set(EXPECTED_FIXTURE_STATUSES))
    missing_fixture = sorted(set(EXPECTED_FIXTURE_STATUSES) - set(observed))
    expectations_match = (
        not missing_expectation
        and not missing_fixture
        and all(EXPECTED_FIXTURE_STATUSES[name] == status for name, status in observed.items())
    )

    forbidden_hits_by_fixture = {
        name: sorted(report["independence"]["forbidden_hits"]) for name, report in reports
    }
    forbidden_hits = sorted(
        {hit for hits in forbidden_hits_by_fixture.values() for hit in hits}
    )
    boundary_by_fixture = {
        name: report["independence"]["information_boundary_all_false"] is True
        for name, report in reports
    }
    information_boundary_all_false = bool(boundary_by_fixture) and all(
        boundary_by_fixture.values()
    )
    request_sha256 = {
        name: str(report["sensitivity"]["request_sha256"]) for name, report in reports
    }
    report_sha256 = {
        name: str(report["sensitivity"]["report_sha256"]) for name, report in reports
    }
    identity = reports[0][1]["sensitivity"]["issue_340_identity"]

    statuses: dict[str, int] = {}
    for status in observed.values():
        statuses[status] = statuses.get(status, 0) + 1

    independence_clean = not forbidden_hits and information_boundary_all_false
    status = STATUS_READY if (expectations_match and independence_clean) else STATUS_NEEDS_FIXES

    provenance = {
        "schema": PROVENANCE_SCHEMA,
        "issue": ISSUE,
        "parent_issue": PARENT_ISSUE,
        "next_issue": NEXT_ISSUE,
        "run_id": RUN_ID,
        "run_dir": RUN_REL,
        "chain": {
            "T1_contract": "contracts/training/model-b-hero-robustness-input.schema.json",
            "T2_fixtures": "tests/fixtures/model_b_robustness_consumer",
            "T4_projection": "tools/simulation/model_b_preflop_sensitivity_harness.py::project_robustness_input",
            "T5_consumer_cli": CLI_REL,
            "T7_run_builder": BUILDER_REL,
        },
        "generator": {
            "tool": BUILDER_REL,
            "consumer_cli": CLI_REL,
            "regeneration_command": regeneration_command(),
            "check_command": f"PYTHONPATH=. python3 {BUILDER_REL} --check",
            "determinism_command": f"PYTHONPATH=. python3 {BUILDER_REL} --verify-determinism",
            "determinism_guard": (
                "the consumer CLI runs twice; the run is written only when both "
                "passes are byte-identical"
            ),
            "verified_by": TEST_REL,
        },
        "inputs": _input_manifest(inputs),
        "source_issue_340_identity": dict(identity),
        "boundaries": {
            "real_hero_results_consumed": False,
            "real_sensitivity_executed": False,
            "real_issue_314_consumed": False,
            "real_issue_367_consumed": False,
            "validation_consumed": False,
            "test_consumed": False,
            "model_a_consumed": False,
            "hero_ev_consumed": False,
            "recommendation_consumed": False,
            "automatic_promotion": False,
            "active_model_b_changed": False,
            "production_effect": "NONE",
            "parent_closed": False,
            "next_issue": NEXT_ISSUE,
        },
        "summary": {
            "fixture_count": len(reports),
            "statuses": dict(sorted(statuses.items())),
        },
    }

    fixture_outputs = {
        "schema": FIXTURE_OUTPUTS_SCHEMA,
        "issue": ISSUE,
        "run_id": RUN_ID,
        "consumer_report_schema": "hero-model-b-robustness-consumer-report/v1",
        "fixture_count": len(reports),
        "statuses": dict(sorted(statuses.items())),
        "fixtures": [
            {
                "fixture": name,
                "decision_id": report["decision_id"],
                "status": report["status"],
                "reason_codes": list(report["reason_codes"]),
                "request_sha256": report["sensitivity"]["request_sha256"],
                "report_sha256": report["sensitivity"]["report_sha256"],
            }
            for name, report in reports
        ],
        "reports": [
            {"fixture": name, "report": report} for name, report in reports
        ],
    }

    independence_proof = {
        "schema": INDEPENDENCE_PROOF_SCHEMA,
        "issue": ISSUE,
        "run_id": RUN_ID,
        "forbidden_hits": forbidden_hits,
        "information_boundary_all_false": information_boundary_all_false,
        "independence_clean": independence_clean,
        "forbidden_features_scanned": sorted(FORBIDDEN_MODEL_FEATURES),
        "forbidden_alternative_leak_fields_scanned": sorted(
            FORBIDDEN_ALTERNATIVE_LEAK_FIELDS
        ),
        "forbidden_hits_by_fixture": forbidden_hits_by_fixture,
        "information_boundary_all_false_by_fixture": boundary_by_fixture,
        "projected_request_sha256": request_sha256,
        "consumer_report_sha256": report_sha256,
        "model_a_consumed": False,
        "hero_ev_consumed": False,
        "recommendation_consumed": False,
        "route_as_predictive_target": False,
    }

    result: dict[str, Any] = {
        "schema": RESULT_SCHEMA,
        "issue": ISSUE,
        "run_id": RUN_ID,
        "run_dir": RUN_REL,
        "parent_issue": PARENT_ISSUE,
        "next_issue": NEXT_ISSUE,
        "status": status,
        "status_vocabulary": list(RUN_STATUSES),
        "real_hero_results_consumed": False,
        "validation_consumed": False,
        "test_consumed": False,
        "parent_closed": False,
        "real_sensitivity_executed": False,
        "real_issue_314_consumed": False,
        "real_issue_367_consumed": False,
        "model_a_consumed": False,
        "hero_ev_consumed": False,
        "recommendation_consumed": False,
        "automatic_promotion": False,
        "active_model_b_changed": False,
        "production_effect": "NONE",
        "fixture_count": len(reports),
        "statuses": dict(sorted(statuses.items())),
        "expected_statuses": {name: EXPECTED_FIXTURE_STATUSES[name] for name in sorted(observed)},
        "observed_statuses": {name: observed[name] for name in sorted(observed)},
        "expectations": {
            "all_match": expectations_match,
            "missing_expectation": missing_expectation,
            "missing_fixture": missing_fixture,
        },
        "independence": {
            "forbidden_hits": forbidden_hits,
            "information_boundary_all_false": information_boundary_all_false,
        },
        "dod": {
            "artifacts_present": True,
            "json_readable": True,
            "flags_recorded": True,
            "fixture_outputs_complete": len(reports) == len(EXPECTED_FIXTURE_STATUSES),
            "expected_statuses_matched": expectations_match,
            "independence_clean": independence_clean,
            "regeneration_command_provided": True,
            "deterministic_sha256_verified": True,
            "issue_315_remains_open_documented": True,
            "real_sensitivity_not_executed_documented": True,
        },
        "determinism": {
            "regeneration_command": regeneration_command(),
            "verify_command": f"PYTHONPATH=. python3 {BUILDER_REL} --verify-determinism",
            "verified_by": TEST_REL,
            "guarantee": "two regenerations over the same inputs are byte-identical",
        },
    }

    summary_md = _summary_lines(reports, result).encode("utf-8")

    artifacts: dict[str, bytes] = {
        "PROVENANCE.json": _json_bytes(provenance),
        "FIXTURE_OUTPUTS.json": _json_bytes(fixture_outputs),
        "INDEPENDENCE_PROOF.json": _json_bytes(independence_proof),
        "SUMMARY.md": summary_md,
    }
    result["artifacts"] = {
        name: _sha256_bytes(data) for name, data in sorted(artifacts.items())
    }
    artifacts["RESULT.json"] = _json_bytes(result)
    return artifacts


def build_run_artifacts(inputs: RunInputs | None = None) -> dict[str, bytes]:
    """One build pass: run the CLI T5 and assemble every artifact in memory."""
    inputs = inputs if inputs is not None else RunInputs()
    with tempfile.TemporaryDirectory(prefix="issue425-consumer-cli-") as tmp:
        reports = _consume_via_cli(inputs, Path(tmp))
    return _build_artifacts(reports, inputs)


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
    artifacts = _regenerate(inputs)
    target = Path(out_dir)
    target.mkdir(parents=True, exist_ok=True)
    for name in ARTIFACT_NAMES:
        (target / name).write_bytes(artifacts[name])
    return {name: _sha256_bytes(artifacts[name]) for name in ARTIFACT_NAMES}


def check_run(
    out_dir: Path | str = RUN_DIR,
    *,
    inputs: RunInputs | None = None,
) -> dict[str, Any]:
    """Compare a fresh single build against the persisted artifacts."""
    fresh = build_run_artifacts(inputs)
    target = Path(out_dir)
    mismatches: list[str] = []
    missing: list[str] = []
    digests: dict[str, str] = {}
    for name in ARTIFACT_NAMES:
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
    artifacts = _regenerate(inputs)
    return {
        "deterministic": True,
        "sha256": {name: _sha256_bytes(artifacts[name]) for name in ARTIFACT_NAMES},
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=RUN_DIR,
        help="run directory to write (default: the committed run)",
    )
    parser.add_argument("--fixtures-dir", "--fixture-dir", dest="fixtures_dir", type=Path, default=DEFAULT_FIXTURES_DIR)
    parser.add_argument("--context", type=Path, default=DEFAULT_CONTEXT_PATH)
    parser.add_argument("--model-b-run", type=Path, default=DEFAULT_SOURCE_340_DIR)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--summary", type=Path)
    parser.add_argument("--result", type=Path)
    parser.add_argument("--provenance", type=Path)
    parser.add_argument("--check", action="store_true", help="fail if the run drifts from a fresh build")
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

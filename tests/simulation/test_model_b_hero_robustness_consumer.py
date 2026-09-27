#!/usr/bin/env python3
"""Consumer acceptance tests for the #425 Hero -> Model B robustness chain (``backlog-m9j``).

The consumer under test is the single callable #425 entry point,
``tools/simulation/model_b_hero_robustness_adapter.run_fixture`` (task
``backlog-m59``), which chains the fail-closed #425 input contract
(``backlog-uso``), the deterministic status classifier (``backlog-nhg``) and the
synthetic-only #344 sensitivity harness.

The suite covers the ticket's eight points on the committed synthetic fixtures
of ``tests/fixtures/model_b_hero_robustness/`` plus derived in-memory variants
(no fixture file is ever written or edited):

1. ``schema_mismatch.json`` fails closed with an explicit ``SCHEMA_MISMATCH``
   reason code: no report, no status, CLI exit code 2;
2. a missing ``provenance`` / ``support`` block is an explicit
   ``MISSING_PROVENANCE`` / ``MISSING_SUPPORT`` rejection that never silently
   upgrades to a supported verdict;
3. ``ood_unsupported.json`` is ``OOD_UNTESTABLE``, the most severe status;
4. ``too_close.json`` stays ``TOO_CLOSE`` and is never requalified
   ``CONSISTENT`` / ``SENSITIVE``;
5. ``sparse_high_uncertainty.json`` is ``INSUFFICIENT_SUPPORT``;
6. ``multi_sizing.json`` classification is deterministic and ``SENSITIVE``
   because the sizing variation sits outside the close band but inside the
   sensitivity band; the derived below/above-band variants follow the T4
   precedence (``TOO_CLOSE`` / ``CONSISTENT``) and every report status equals
   the T4 classifier status for the same fixture;
7. re-running the same fixtures yields byte-identical reports with identical
   ``harness_request_sha256`` / ``harness_report_sha256`` values, including
   across two distinct ``PYTHONHASHSEED`` values;
8. Model A / B independence: the projected #344 request carries no
   ``FORBIDDEN_MODEL_FEATURES`` key, its alternatives are public action identity
   only and its ``information_boundary`` is entirely false.

The suite is synthetic and hermetic: it only reads the committed fixtures, the
public #344 context and the persisted #340 response-to-price documents. It never
opens the real ``#367`` ISO EV run, never reads a VALIDATION/TEST hand and never
performs network I/O (the two determinism subprocesses are local interpreter
runs). Any failure makes the script exit non-zero.

Run it with::

    PYTHONPATH=. python3 tests/simulation/test_model_b_hero_robustness_consumer.py
"""
from __future__ import annotations

import copy
import io
import json
import os
import subprocess
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any, Callable, Mapping
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.simulation import model_b_hero_robustness_adapter as adapter  # noqa: E402
from tools.simulation import model_b_hero_robustness_classify as classifier  # noqa: E402
from tools.simulation import model_b_hero_robustness_contract as contract  # noqa: E402
from tools.simulation import model_b_preflop_sensitivity_harness as harness  # noqa: E402

FIXTURES = ROOT / "tests/fixtures/model_b_hero_robustness"
CONTEXT_PATH = (
    ROOT / "tests/fixtures/model_b_preflop_sensitivity/synthetic_sb_two_limpers_context.json"
)
ADAPTER_PATH = ROOT / "tools/simulation/model_b_hero_robustness_adapter.py"
REPORT_SCHEMA_PATH = ROOT / "contracts/training/hero-model-b-robustness-consumer-report.schema.json"

#: Assembled so this guard does not itself hard-code the forbidden run name.
FORBIDDEN_RUN_MARKER = "real" + "_iso" + "_ev"

#: Every committed fixture that must produce a report, with its expected #425 status.
FIXTURE_STATUSES = {
    "robust_consistent.json": "CONSISTENT",
    "multi_sizing.json": "SENSITIVE",
    "too_close.json": "TOO_CLOSE",
    "sparse_high_uncertainty.json": "INSUFFICIENT_SUPPORT",
    "ood_unsupported.json": "OOD_UNTESTABLE",
}
INVALID_FIXTURE = "schema_mismatch.json"

#: Exact key set the projection may emit for one alternative: public action
#: identity only -- no EV / uncertainty / support / route / posterior reference.
PROJECTED_ALTERNATIVE_KEYS = frozenset(
    {"alternative_id", "action", "target_total_bb", "incremental_cost_bb"}
)

#: The complete forbidden Model A / EV / recommendation / route vocabulary.
FORBIDDEN_TOKENS = frozenset(harness.FORBIDDEN_MODEL_FEATURES) | frozenset(
    harness.FORBIDDEN_ALTERNATIVE_LEAK_FIELDS
)

_DOCS_340_CACHE: dict[str, Any] | None = None
_CONTEXT_CACHE: Mapping[str, Any] | None = None
_REPORT_CACHE: dict[str, dict[str, Any]] = {}


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def check(condition: object, message: str) -> None:
    """Fail this section with a readable message when ``condition`` is falsy."""
    if not condition:
        raise AssertionError(message)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def fixture(name: str) -> dict[str, Any]:
    """Return a fresh deep copy of one committed synthetic fixture."""
    return copy.deepcopy(load_json(FIXTURES / name))


def context() -> Mapping[str, Any]:
    global _CONTEXT_CACHE
    if _CONTEXT_CACHE is None:
        _CONTEXT_CACHE = load_json(CONTEXT_PATH)
    return _CONTEXT_CACHE


def docs_340() -> dict[str, Any]:
    """Load the five persisted #340 documents once for the whole suite."""
    global _DOCS_340_CACHE
    if _DOCS_340_CACHE is None:
        _DOCS_340_CACHE = adapter.load_source_340_docs()
    return _DOCS_340_CACHE


def fresh_report(name: str) -> dict[str, Any]:
    """Consume one fixture end to end from disk, without any caching."""
    return adapter.run_fixture(FIXTURES / name, source_340=docs_340())


def report_for(name: str) -> dict[str, Any]:
    """Cached :func:`fresh_report` for the read-only assertions."""
    if name not in _REPORT_CACHE:
        _REPORT_CACHE[name] = fresh_report(name)
    return copy.deepcopy(_REPORT_CACHE[name])


def expect_contract_error(
    call: Callable[[], Any],
    expected_code: str,
) -> contract.RobustnessContractError:
    try:
        call()
    except contract.RobustnessContractError as exc:
        check(
            exc.reason_code == expected_code,
            f"expected reason_code {expected_code!r}, got {exc.reason_code!r} ({exc.message})",
        )
        return exc
    raise AssertionError(f"expected a fail-closed {expected_code} rejection")


def expect_adapter_error(
    call: Callable[[], Any],
    expected_code: str,
) -> adapter.AdapterError:
    try:
        call()
    except adapter.AdapterError as exc:
        check(
            exc.reason_code == expected_code,
            f"expected reason_code {expected_code!r}, got {exc.reason_code!r} ({exc.message})",
        )
        return exc
    raise AssertionError(f"expected a fail-closed {expected_code} rejection")


def alternative_keys(alternative: Mapping[str, Any]) -> frozenset[str]:
    return frozenset(str(key) for key in alternative)


def best_alternative_ev(document: Mapping[str, Any]) -> float:
    entry = document["hero_entry"]
    return max(float(alternative["ev"]) for alternative in entry["alternatives"])


def iter_keys(value: Any, path: str = "$"):
    """Yield ``(path, key)`` for every mapping key found anywhere in ``value``."""
    if isinstance(value, Mapping):
        for key, child in value.items():
            yield f"{path}.{key}", str(key)
            yield from iter_keys(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from iter_keys(child, f"{path}[{index}]")


def leaked_feature_paths(request: Mapping[str, Any]) -> list[str]:
    """Independent forbidden-feature walk over a projected request.

    Mirrors the consumer rule (the ``information_boundary`` block enumerates the
    boundary flag names themselves and is asserted all-false separately) but
    re-implements the walk here, so the independence proof does not trust the
    module under test.
    """
    scannable = {key: value for key, value in request.items() if key != "information_boundary"}
    hits: list[str] = []
    for path, key in iter_keys(scannable):
        lowered = key.lower()
        if lowered in FORBIDDEN_TOKENS or lowered.startswith("model_a"):
            hits.append(path)
    return sorted(set(hits))


def cli(
    fixture_path: Path,
    out_path: Path,
    *,
    extra_env: Mapping[str, str] | None = None,
) -> "subprocess.CompletedProcess[str]":
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, str(ADAPTER_PATH), "--fixture", str(fixture_path), "--out", str(out_path)],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
    )


# --------------------------------------------------------------------------- #
# (1) schema mismatch => fail-closed with a reason_code
# --------------------------------------------------------------------------- #
def test_schema_mismatch_fails_closed() -> None:
    document = fixture(INVALID_FIXTURE)
    check(
        document["schema"] == "hero-model-b-robustness-input/v2",
        "the committed schema_mismatch.json must carry the v2 schema id",
    )
    check(
        document["schema"] != contract.INPUT_SCHEMA,
        "the mismatch fixture must not carry the shipped #425 schema id",
    )

    error = expect_contract_error(
        lambda: contract.validate_robustness_input(document), "SCHEMA_MISMATCH"
    )
    check(
        "SCHEMA_MISMATCH" in error.reason_codes,
        f"the fail-closed catalogue must carry SCHEMA_MISMATCH: {error.reason_codes}",
    )
    check(
        error.to_dict()["status"] == "FAIL_CLOSED",
        "the contract error payload must be FAIL_CLOSED",
    )

    # The only defect is the schema id: repairing it in memory makes the same
    # fixture validate, so the rejection really is the schema guard.
    repaired = fixture(INVALID_FIXTURE)
    repaired["schema"] = contract.INPUT_SCHEMA
    check(
        contract.validate_robustness_input(repaired) is repaired,
        "the repaired copy must validate (the schema id is the only defect)",
    )

    # The consumer refuses the fixture and emits no report and no status.
    adapter_error = expect_adapter_error(
        lambda: adapter.run_fixture(FIXTURES / INVALID_FIXTURE, source_340=docs_340()),
        "SCHEMA_MISMATCH",
    )
    payload = adapter_error.to_dict()
    check(payload["outcome"] == "FAIL_CLOSED", payload)
    check(payload["schema"] == adapter.ADAPTER_ERROR_SCHEMA, payload)
    check("status" not in payload, "a fail-closed payload never carries a robustness status")

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "report.json"
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = adapter.main(
                ["--fixture", str(FIXTURES / INVALID_FIXTURE), "--out", str(out)]
            )
        check(code == 2, f"the CLI must exit 2 on a fail-closed fixture, got {code}")
        check(not out.exists(), "a fail-closed fixture must never write a report")
        check(stdout.getvalue() == "", "a fail-closed fixture must print no report on stdout")
        cli_payload = json.loads(stderr.getvalue())
        check(cli_payload["reason_code"] == "SCHEMA_MISMATCH", cli_payload)
        check("status" not in cli_payload, "the CLI payload must carry no status")


# --------------------------------------------------------------------------- #
# (2) missing provenance / support => explicit rejection
# --------------------------------------------------------------------------- #
def test_missing_provenance_and_support_are_explicit() -> None:
    base = fixture("robust_consistent.json")

    def without_provenance(document: dict[str, Any]) -> None:
        document.pop("provenance")

    def incomplete_provenance(document: dict[str, Any]) -> None:
        document["provenance"].pop("test_consumed")

    def opened_provenance(document: dict[str, Any]) -> None:
        document["provenance"]["validation_consumed"] = True

    def hero_without_support(document: dict[str, Any]) -> None:
        document["hero_entry"].pop("support")

    def alternative_without_support(document: dict[str, Any]) -> None:
        document["hero_entry"]["alternatives"][0].pop("support")

    def alternative_null_support(document: dict[str, Any]) -> None:
        document["hero_entry"]["alternatives"][0]["support"] = None

    cases: tuple[tuple[str, Callable[[dict[str, Any]], None]], ...] = (
        ("MISSING_PROVENANCE", without_provenance),
        ("MISSING_PROVENANCE", incomplete_provenance),
        ("MISSING_PROVENANCE", opened_provenance),
        ("MISSING_SUPPORT", hero_without_support),
        ("MISSING_SUPPORT", alternative_without_support),
        ("MISSING_SUPPORT", alternative_null_support),
    )

    for expected_code, mutate in cases:
        document = copy.deepcopy(base)
        mutate(document)

        error = expect_contract_error(
            lambda doc=document: contract.validate_robustness_input(doc), expected_code
        )
        check(error.to_dict()["status"] == "FAIL_CLOSED", error.to_dict())
        check(bool(error.message), "the rejection must carry an explicit message")

        # The consumer itself (report builder) must refuse as well.
        adapter_error = expect_adapter_error(
            lambda doc=document: adapter.build_report(doc, context=context(), **docs_340()),
            expected_code,
        )
        check(
            "status" not in adapter_error.to_dict(),
            "no failing input may ever produce a status",
        )

        # A missing/declared-null support block is never silently upgraded by the
        # classifier either: it either raises explicitly or returns a
        # non-CONSISTENT verdict with non-empty reason codes. Provenance is
        # enforced by the contract layer above, so it is checked there (the
        # consumer never classifies an input whose provenance failed).
        if expected_code == "MISSING_SUPPORT":
            try:
                result = classifier.classify(document)
            except classifier.RobustnessClassifyError as exc:
                check(bool(exc.reason_code), "the classifier error must carry a reason code")
            else:
                check(
                    result["status"] in classifier.STATUSES,
                    f"non-vocabulary status: {result['status']!r}",
                )
                check(
                    result["status"] != "CONSISTENT",
                    "a missing support block may never be silently upgraded",
                )
                check(bool(result["reason_codes"]), "the verdict must carry reason codes")

    # The incomplete-provenance reason catalogue is explicit too.
    document = copy.deepcopy(base)
    incomplete_provenance(document)
    error = expect_contract_error(
        lambda: contract.validate_robustness_input(document), "MISSING_PROVENANCE"
    )
    check(
        "PROVENANCE_INCOMPLETE" in error.reason_codes,
        f"the ordered catalogue must name the incompleteness: {error.reason_codes}",
    )

    # A present-but-null support verdict is "not evaluated", never supported.
    classifiable = copy.deepcopy(base)
    classifiable["hero_entry"]["support"] = None
    verdict = classifier.classify(classifiable)
    check(verdict["status"] == "OOD_UNTESTABLE", verdict)
    check("SUPPORT_MISSING" in verdict["reason_codes"], verdict)


# --------------------------------------------------------------------------- #
# (3) OOD => OOD_UNTESTABLE
# --------------------------------------------------------------------------- #
def test_ood_fixture_is_ood_untestable() -> None:
    report = report_for("ood_unsupported.json")
    check(report["status"] == "OOD_UNTESTABLE", report)
    check(report["status"] in adapter.STATUSES, "the status must be in the closed vocabulary")
    check(
        set(report["reason_codes"])
        <= set(classifier.REASON_CODES_BY_STATUS["OOD_UNTESTABLE"]),
        f"non-OOD reason codes: {report['reason_codes']}",
    )
    check(bool(report["reason_codes"]), "an OOD verdict must carry reason codes")
    check(
        {"SUPPORT_OOD", "SUPPORT_STATUS_OOD"} & set(report["reason_codes"]),
        f"the OOD reason codes must be explicit: {report['reason_codes']}",
    )

    # Precedence: even when every declared support verdict is bribed to
    # CONSISTENT, the OOD environment keeps the entry untestable.
    bribed = fixture("ood_unsupported.json")
    entry = bribed["hero_entry"]
    for alternative in [entry, *entry["alternatives"]]:
        alternative["support"] = {"status": "CONSISTENT", "tier": "HIGH", "ood": True}
    result = classifier.classify(bribed)
    check(
        result["status"] == "OOD_UNTESTABLE",
        f"an OOD environment may never be requalified: {result}",
    )
    check(
        result["status"] != "CONSISTENT",
        "OOD_UNTESTABLE has absolute precedence over CONSISTENT",
    )

    # An OOD alternative (not only the Hero entry) is enough to make the entry
    # untestable.
    alternative_ood = fixture("robust_consistent.json")
    alternative_ood["hero_entry"]["alternatives"][0]["support"] = {
        "status": "CONSISTENT",
        "tier": "HIGH",
        "ood": True,
    }
    result = classifier.classify(alternative_ood)
    check(result["status"] == "OOD_UNTESTABLE", result)


# --------------------------------------------------------------------------- #
# (4) too-close is preserved (never overwritten)
# --------------------------------------------------------------------------- #
def test_too_close_is_preserved() -> None:
    report = report_for("too_close.json")
    check(report["status"] == "TOO_CLOSE", report)
    check(
        report["status"] not in {"CONSISTENT", "SENSITIVE"},
        f"TOO_CLOSE must never be requalified: {report['status']}",
    )
    check(
        {"ADVANTAGE_WITHIN_TOLERANCE", "PAIRED_DELTA_WITHIN_TOLERANCE"}
        & set(report["reason_codes"]),
        f"the close-band reason must be explicit: {report['reason_codes']}",
    )
    check(
        set(report["reason_codes"]) <= set(classifier.REASON_CODES_BY_STATUS["TOO_CLOSE"]),
        f"non-close reason codes: {report['reason_codes']}",
    )

    # Bribe the declared support up to CONSISTENT/VERY_HIGH and flatten the
    # paired deltas: TOO_CLOSE still wins because the advantage itself sits in
    # the declared noise band.
    bribed = fixture("too_close.json")
    entry = bribed["hero_entry"]
    entry["paired_delta"] = 0.0
    for alternative in entry["alternatives"]:
        alternative["support"] = {"status": "CONSISTENT", "tier": "VERY_HIGH", "ood": False}
        alternative["paired_delta"] = 0.0
    result = classifier.classify(bribed)
    check(result["status"] == "TOO_CLOSE", result)
    check(
        "ADVANTAGE_WITHIN_TOLERANCE" in result["reason_codes"],
        f"the measured advantage is the refusal reason: {result['reason_codes']}",
    )

    # TOO_CLOSE outranks SENSITIVE when both buckets are filled.
    dual = fixture("multi_sizing.json")
    dual["hero_entry"]["ev"] = best_alternative_ev(dual) + classifier.TOO_CLOSE_DELTA_BB / 2.0
    dual_verdict = classifier.classify(dual)
    check(
        dual_verdict["status"] == "TOO_CLOSE",
        f"TOO_CLOSE must precede SENSITIVE: {dual_verdict}",
    )
    check("ADVANTAGE_WITHIN_TOLERANCE" in dual_verdict["reason_codes"], dual_verdict)

    # The bands themselves are explicit, ordered policy constants.
    check(
        0.0 < classifier.TOO_CLOSE_DELTA_BB < classifier.SENSITIVE_DELTA_BB,
        "the close band must be a strict subset of the sensitivity band",
    )


# --------------------------------------------------------------------------- #
# (5) sparse / high uncertainty => INSUFFICIENT_SUPPORT
# --------------------------------------------------------------------------- #
def test_sparse_high_uncertainty_is_insufficient_support() -> None:
    report = report_for("sparse_high_uncertainty.json")
    check(report["status"] == "INSUFFICIENT_SUPPORT", report)
    check(
        set(report["reason_codes"])
        <= set(classifier.REASON_CODES_BY_STATUS["INSUFFICIENT_SUPPORT"]),
        f"non-support reason codes: {report['reason_codes']}",
    )
    check(
        {"CI95_WIDTH_EXCEEDS_POLICY", "SPARSE_SUPPORT_TIER", "SUPPORT_STATUS_INSUFFICIENT"}
        <= set(report["reason_codes"]),
        f"the sparsity and the CI95 width must both be explicit: {report['reason_codes']}",
    )

    document = fixture("sparse_high_uncertainty.json")
    entry = document["hero_entry"]
    check(
        float(entry["uncertainty"]["width_bb"]) > classifier.MAX_CI95_WIDTH_BB,
        "the fixture CI95 width must exceed the policy maximum",
    )

    # INSUFFICIENT_SUPPORT outranks TOO_CLOSE: putting the standing inside the
    # close band must not weaken the sparse verdict.
    bribed = fixture("sparse_high_uncertainty.json")
    bribed["hero_entry"]["ev"] = (
        best_alternative_ev(bribed) + classifier.TOO_CLOSE_DELTA_BB / 2.0
    )
    result = classifier.classify(bribed)
    check(
        result["status"] == "INSUFFICIENT_SUPPORT",
        f"INSUFFICIENT_SUPPORT must precede TOO_CLOSE: {result}",
    )


# --------------------------------------------------------------------------- #
# (6) multi-sizing => deterministic SENSITIVE classification
# --------------------------------------------------------------------------- #
def test_multi_sizing_is_deterministic_sensitive() -> None:
    report = report_for("multi_sizing.json")
    check(report["status"] == "SENSITIVE", report)
    check(
        set(report["reason_codes"]) <= set(classifier.REASON_CODES_BY_STATUS["SENSITIVE"]),
        f"non-sensitive reason codes: {report['reason_codes']}",
    )
    check(
        {"ADVANTAGE_WITHIN_SENSITIVITY_BAND", "SIZING_VARIATION_WITHIN_SENSITIVITY_BAND"}
        <= set(report["reason_codes"]),
        f"the sizing variation must be explicit: {report['reason_codes']}",
    )

    document = fixture("multi_sizing.json")
    advantage = float(document["hero_entry"]["ev"]) - best_alternative_ev(document)
    check(
        classifier.TOO_CLOSE_DELTA_BB < advantage <= classifier.SENSITIVE_DELTA_BB,
        f"the fixture advantage {advantage} must sit outside the close band and "
        f"inside the sensitivity band",
    )

    # Deterministic: repeated calls and a reordered alternative list agree.
    first = classifier.classify(document)
    second = classifier.classify(document)
    check(first == second, f"classification is not deterministic: {first} != {second}")
    shuffled = fixture("multi_sizing.json")
    shuffled["hero_entry"]["alternatives"] = list(
        reversed(shuffled["hero_entry"]["alternatives"])
    )
    check(
        classifier.classify(shuffled) == first,
        "the order of alternatives must not change the verdict",
    )

    # Below the close band: TOO_CLOSE (T4 precedence), never SENSITIVE.
    inside = fixture("multi_sizing.json")
    inside["hero_entry"]["ev"] = (
        best_alternative_ev(inside) + classifier.TOO_CLOSE_DELTA_BB / 2.0
    )
    inside_verdict = classifier.classify(inside)
    check(
        inside_verdict == classifier.classify(inside),
        "the close-band verdict must be deterministic",
    )
    check(
        inside_verdict["status"] == "TOO_CLOSE",
        f"a variation inside the close band is TOO_CLOSE: {inside_verdict}",
    )

    # Above the sensitivity band: CONSISTENT for the settled synthetic entry.
    outside = fixture("robust_consistent.json")
    outside_advantage = float(outside["hero_entry"]["ev"]) - best_alternative_ev(outside)
    check(
        outside_advantage > classifier.SENSITIVE_DELTA_BB,
        f"robust_consistent.json must sit outside the sensitivity band: {outside_advantage}",
    )
    outside_verdict = classifier.classify(outside)
    check(
        outside_verdict["status"] == "CONSISTENT",
        f"a settled standing is CONSISTENT: {outside_verdict}",
    )

    # The consumer report must stay coherent with the T4 classifier for every
    # committed fixture (one source of truth, no re-derivation in the adapter).
    for name, expected in FIXTURE_STATUSES.items():
        report = report_for(name)
        t4 = classifier.classify(fixture(name))
        check(
            report["status"] == t4["status"] == expected,
            f"{name}: report={report['status']!r} t4={t4['status']!r} expected={expected!r}",
        )
        check(
            report["reason_codes"] == t4["reason_codes"],
            f"{name}: report reason codes {report['reason_codes']} != T4 {t4['reason_codes']}",
        )


# --------------------------------------------------------------------------- #
# (7) determinism: same fixtures => same reports and sha256
# --------------------------------------------------------------------------- #
def test_same_fixtures_same_outputs() -> None:
    for name in sorted(FIXTURE_STATUSES):
        first = fresh_report(name)
        second = fresh_report(name)

        check(first == second, f"{name}: two runs must yield the same report")
        check(
            adapter.render_report(first) == adapter.render_report(second),
            f"{name}: the rendered report must be byte-identical",
        )
        check(
            harness.canonical_sha256(first) == harness.canonical_sha256(second),
            f"{name}: canonical report sha256 must be stable",
        )
        check(
            first["harness_request_sha256"] == second["harness_request_sha256"],
            f"{name}: projected request sha256 must be stable",
        )
        check(
            first["harness_report_sha256"] == second["harness_report_sha256"],
            f"{name}: #344 harness report sha256 must be stable",
        )
        for key in ("harness_request_sha256", "harness_report_sha256"):
            value = first[key]
            check(
                isinstance(value, str) and len(value) == 64 and value == value.lower(),
                f"{name}: {key} must be a lowercase 64-hex digest, got {value!r}",
            )

    # Cross-process determinism: two local CLI runs under distinct hash seeds
    # must write byte-identical reports.
    with tempfile.TemporaryDirectory() as tmp:
        outputs = []
        for seed in ("0", "424242"):
            out = Path(tmp) / f"report-{seed}.json"
            result = cli(FIXTURES / "multi_sizing.json", out, extra_env={"PYTHONHASHSEED": seed})
            check(result.returncode == 0, f"CLI failed for seed {seed}: {result.stderr}")
            check(out.is_file(), f"CLI did not write the report for seed {seed}")
            outputs.append(out.read_text(encoding="utf-8"))
        check(
            outputs[0] == outputs[1],
            "two CLI runs with different PYTHONHASHSEED must write identical reports",
        )

    # The fail-closed path is deterministic too: same reason code, no report.
    payloads = []
    for _ in range(2):
        try:
            adapter.run_fixture(FIXTURES / INVALID_FIXTURE, source_340=docs_340())
        except adapter.AdapterError as exc:
            payloads.append(json.dumps(exc.to_dict(), sort_keys=True))
        else:
            raise AssertionError("schema_mismatch.json must always fail closed")
    check(payloads[0] == payloads[1], "the fail-closed payload must be deterministic")


# --------------------------------------------------------------------------- #
# (8) Model A / B independence on the projected request
# --------------------------------------------------------------------------- #
def test_projected_request_is_independent_from_model_a() -> None:
    check(
        {"ev_bb", "recommendation", "hero_ev", "route"} <= set(harness.FORBIDDEN_MODEL_FEATURES),
        "the forbidden vocabulary must be non-empty and carry the expected tokens",
    )
    check(
        REPORT_SCHEMA_PATH.is_file(),
        f"the shipped #425 report contract is missing: {REPORT_SCHEMA_PATH}",
    )

    for name in sorted(FIXTURE_STATUSES):
        document = fixture(name)
        request = contract.project_to_harness_request(document, context())

        check(
            contract.check_forbidden_features(request) == [],
            f"{name}: the #425 leak scan must find nothing",
        )
        check(
            leaked_feature_paths(request) == [],
            f"{name}: the independent key walk must find no forbidden feature",
        )

        boundary = request["information_boundary"]
        check(
            set(boundary) == set(contract.INFORMATION_BOUNDARY_FLAGS),
            f"{name}: unexpected information boundary keys {sorted(boundary)}",
        )
        check(
            all(value is False for value in boundary.values()),
            f"{name}: the projected information_boundary must be entirely false: {boundary}",
        )

        for alternative in request["alternatives"]:
            check(
                alternative_keys(alternative) == PROJECTED_ALTERNATIVE_KEYS,
                f"{name}: alternatives must be public action identity only, got "
                f"{sorted(alternative)}",
            )

        report = report_for(name)
        check(
            adapter.validate_report(report) is report,
            f"{name}: the report must satisfy the shipped #425 report contract",
        )
        check(
            all(value is False for value in report["information_boundary"].values()),
            f"{name}: the report information boundary must be entirely false",
        )
        check(
            set(report["information_boundary"]) == set(adapter.REPORT_INFORMATION_BOUNDARY_FLAGS),
            f"{name}: the report must pin every #425 boundary flag",
        )
        for flag in (
            "real_issue_367_consumed",
            "real_issue_314_consumed",
            "validation_consumed",
            "test_consumed",
        ):
            check(
                report["provenance"][flag] is False,
                f"{name}: the report must not claim {flag}",
            )

    # Negative case: an injected forbidden key is refused by the projection guard.
    projection = contract.project_to_harness_request(fixture("too_close.json"), context())
    injections = (
        ("ev_bb", lambda bad: bad["alternatives"][0].__setitem__("ev_bb", 1.0)),
        ("route", lambda bad: bad["alternatives"][0].__setitem__("route", "leaked_route")),
        (
            "support",
            lambda bad: bad["alternatives"][0].__setitem__(
                "support", {"status": "CONSISTENT", "tier": "HIGH", "ood": False}
            ),
        ),
        (
            "uncertainty",
            lambda bad: bad["alternatives"][0].__setitem__(
                "uncertainty", {"ci95": [0.0, 1.0], "width_bb": 1.0, "source": "leak"}
            ),
        ),
        (
            "posterior_refs",
            lambda bad: bad["alternatives"][0].__setitem__("posterior_refs", ["leak"]),
        ),
        ("recommended_action", lambda bad: bad.__setitem__("recommended_action", "ISO@5")),
        ("hero_ev", lambda bad: bad.__setitem__("hero_ev", 1.0)),
        (
            "model_a_policy",
            lambda bad: bad["decision_ref"].__setitem__("model_a_policy", "leak"),
        ),
    )
    for key, mutate in injections:
        leaked = copy.deepcopy(projection)
        mutate(leaked)
        hits = contract.check_forbidden_features(leaked)
        check(
            any(hit.endswith(key) for hit in hits),
            f"the leak scan must catch the injected {key!r}: {hits}",
        )
        expect_contract_error(
            lambda bad=leaked: contract.validate_projected_request(bad), "FORBIDDEN_FEATURE"
        )

    # End to end: even if a future projection leaked, the consumer still fails
    # closed and emits no status.
    leaked_request = copy.deepcopy(projection)
    leaked_request["alternatives"][0]["route"] = "leaked_route"
    with mock.patch.object(adapter, "project_to_harness_request", return_value=leaked_request):
        error = expect_adapter_error(
            lambda: adapter.build_report(
                fixture("too_close.json"), context=context(), **docs_340()
            ),
            "HARNESS_REJECTED",
        )
    check("status" not in error.to_dict(), "a leaked projection may never produce a status")
    check(
        "forbidden" in error.message.lower(),
        f"the harness refusal must name the forbidden feature: {error.message}",
    )

    # Guard: the adapter is never wired to the forbidden real run.
    check(
        FORBIDDEN_RUN_MARKER not in str(adapter.DEFAULT_SOURCE_340_DIR).lower(),
        "the adapter must not read the real #367 ISO EV run",
    )


SECTIONS: tuple[tuple[str, Callable[[], None]], ...] = (
    (
        "(1) schema mismatch fails closed with a reason code",
        test_schema_mismatch_fails_closed,
    ),
    (
        "(2) missing provenance/support is an explicit rejection",
        test_missing_provenance_and_support_are_explicit,
    ),
    ("(3) OOD fixture is OOD_UNTESTABLE", test_ood_fixture_is_ood_untestable),
    ("(4) too-close is preserved and never overwritten", test_too_close_is_preserved),
    (
        "(5) sparse/high uncertainty is INSUFFICIENT_SUPPORT",
        test_sparse_high_uncertainty_is_insufficient_support,
    ),
    (
        "(6) multi-sizing is deterministically SENSITIVE",
        test_multi_sizing_is_deterministic_sensitive,
    ),
    ("(7) same fixtures produce the same reports and sha256", test_same_fixtures_same_outputs),
    (
        "(8) projected request is Model A/B independent",
        test_projected_request_is_independent_from_model_a,
    ),
)


def main() -> int:
    failures: list[str] = []
    passed = 0
    for label, section in SECTIONS:
        try:
            section()
        except AssertionError as exc:
            message = str(exc) or "assertion failed"
            failures.append(f"{label}: {message}")
            print(f"FAIL {label}: {message}", file=sys.stderr)
        except Exception as exc:  # noqa: BLE001 - report every section, keep going
            message = f"{type(exc).__name__}: {exc}"
            failures.append(f"{label}: {message}")
            print(f"ERROR {label}: {message}", file=sys.stderr)
        else:
            passed += 1
            print(f"ok   {label}")

    if failures:
        print(
            f"#425 Hero -> Model B robustness consumer: FAIL "
            f"({len(failures)}/{len(SECTIONS)} sections)",
            file=sys.stderr,
        )
        return 1

    print(
        f"#425 Hero -> Model B robustness consumer ({passed}/{len(SECTIONS)} sections): PASS"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

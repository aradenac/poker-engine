#!/usr/bin/env python3
"""Acceptance tests for the fail-closed Hero -> Model B robustness consumer (#425).

This is the ``backlog-hae`` acceptance suite. It covers exactly the six ticket
points plus the mandated negative case:

(a) a schema mismatch fails closed with an explicit ``reason_code``;
(b) a missing ``provenance`` or per-alternative ``support`` block is explicit:
    the consumer raises a ``reason_code`` and the classifier yields non-empty
    ``reason_codes`` instead of a silent/empty status;
(c) an out-of-distribution fixture is classified ``OOD_UNTESTABLE``;
(d) a too-close fixture stays ``TOO_CLOSE`` and is never requalified
    ``CONSISTENT`` or ``SENSITIVE``;
(e) the same fixtures produce byte-identical reports and identical sha256
    values across two independent passes;
(f) Model A / Model B independence: every forbidden feature is absent from the
    projected ``#344`` request and the ``information_boundary`` is entirely
    false -- plus a negative case injecting a forbidden key
    (``ev_bb`` / ``recommended_action`` / ``route`` / ``model_a_*``) and
    checking that the consumer refuses it.

The whole suite is synthetic and hermetic: it only reads the committed
synthetic fixtures, the public sensitivity context, the ``#340`` price-response
run artifacts and the source of the modules under test. It never opens the real
``#367`` ISO EV run directory, never reads a VALIDATION/TEST hand and never
performs network I/O. Any failure makes the script exit non-zero.

Run it with::

    PYTHONPATH=. python3 tests/simulation/test_model_b_hero_robustness_consumer.py
"""
from __future__ import annotations

import copy
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.simulation import model_b_hero_robustness_consumer as consumer  # noqa: E402
from tools.simulation.model_b_hero_robustness_consumer import (  # noqa: E402
    BATCH_REPORT_SCHEMA,
    CONSUMER_REPORT_SCHEMA,
    DEFAULT_SOURCE_340_DIR,
    ConsumerError,
    assert_source_artifact_allowed,
    build_consumer_report,
    consume_batch,
    consume_fixture,
    independence_guard,
    load_source_340_docs,
    main,
    scan_forbidden_features,
    validate_fixture,
)
from tools.simulation.model_b_hero_robustness_status import (  # noqa: E402
    REASON_CODES,
    STATUSES,
    classify_robustness,
)
from tools.simulation.model_b_preflop_sensitivity_harness import (  # noqa: E402
    FORBIDDEN_ALTERNATIVE_LEAK_FIELDS,
    FORBIDDEN_MODEL_FEATURES,
    canonical_sha256,
    load_json,
    project_robustness_input,
)

FIXTURES = ROOT / "tests/fixtures/model_b_robustness_consumer"
CONTEXT = ROOT / "tests/fixtures/model_b_preflop_sensitivity/synthetic_sb_two_limpers_context.json"
MODULE_PATH = ROOT / "tools/simulation/model_b_hero_robustness_consumer.py"

#: Expected classifier verdict for every synthetic fixture of the T2 folder.
FIXTURE_STATUSES = {
    "robust_recommendation.json": "CONSISTENT",
    "too_close.json": "TOO_CLOSE",
    "sparse_high_uncertainty.json": "INSUFFICIENT_SUPPORT",
    "ood_unsupported.json": "OOD_UNTESTABLE",
    "multiple_sizings.json": "SENSITIVE",
}

#: The full forbidden Model A / EV / recommendation / route vocabulary.
FORBIDDEN_TOKENS = frozenset(FORBIDDEN_MODEL_FEATURES) | frozenset(
    FORBIDDEN_ALTERNATIVE_LEAK_FIELDS
)

#: Exact key set the projection may emit for one alternative: public action
#: identity only, no EV / uncertainty / route / support / recommendation.
PROJECTED_ALTERNATIVE_KEYS = frozenset(
    {"alternative_id", "action", "target_total_bb", "incremental_cost_bb"}
)

#: Assembled so this guard does not itself hard-code the forbidden run name.
FORBIDDEN_RUN_MARKER = "real" + "_iso" + "_ev"


def _docs_340() -> dict:
    cache = getattr(_docs_340, "_cache", None)
    if cache is None:
        cache = load_source_340_docs()
        _docs_340._cache = cache  # type: ignore[attr-defined]
    return cache


def _report(name: str) -> dict:
    """Return a deep copy of the report for one committed fixture."""
    cache = getattr(_report, "_cache", None)
    if cache is None:
        cache = {}
        _report._cache = cache  # type: ignore[attr-defined]
    if name not in cache:
        cache[name] = consume_fixture(FIXTURES / name, source_340=_docs_340())
    return copy.deepcopy(cache[name])


def _fresh_report(name: str) -> dict:
    """Return a report recomputed from scratch (no cache), for determinism."""
    return consume_fixture(FIXTURES / name, source_340=_docs_340())


def _projected_request() -> dict:
    return project_robustness_input(
        load_json(FIXTURES / "too_close.json"), context=load_json(CONTEXT)
    )


def _iter_keys(value: object, path: str = "$"):
    """Yield ``(path, key)`` for every mapping key found anywhere in ``value``."""
    if isinstance(value, dict):
        for key, child in value.items():
            yield f"{path}.{key}", str(key)
            yield from _iter_keys(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _iter_keys(child, f"{path}[{index}]")


class AcceptanceTests(unittest.TestCase):
    """One named test per ticket point (a)-(f), plus the negative case."""

    @classmethod
    def setUpClass(cls):
        cls.context = load_json(CONTEXT)
        cls.too_close = load_json(FIXTURES / "too_close.json")
        cls.docs = _docs_340()

    # --- (a) schema mismatch ------------------------------------------------
    def test_a_schema_mismatch_fails_closed(self):
        bad = copy.deepcopy(self.too_close)
        bad["schema"] = "hero-model-b-robustness-input/v2"
        with self.assertRaises(ConsumerError) as caught:
            validate_fixture(bad)
        self.assertEqual(caught.exception.reason_code, "SCHEMA_MISMATCH")
        self.assertEqual(caught.exception.to_dict()["status"], "FAIL_CLOSED")
        self.assertIn("SCHEMA_MISMATCH", str(caught.exception))

    def test_a_schema_mismatch_never_yields_a_report(self):
        bad = copy.deepcopy(self.too_close)
        bad["schema"] = "poker-preflop-decision/v1"
        with self.assertRaises(ConsumerError) as caught:
            build_consumer_report(bad, context=self.context, **self.docs)
        self.assertEqual(caught.exception.reason_code, "SCHEMA_MISMATCH")

    def test_a_source_kind_mismatch_fails_closed(self):
        bad = copy.deepcopy(self.too_close)
        bad["source_kind"] = "REAL_ISSUE_314"
        with self.assertRaises(ConsumerError) as caught:
            validate_fixture(bad)
        self.assertEqual(caught.exception.reason_code, "SOURCE_KIND_MISMATCH")

    # --- (b) missing provenance / support is explicit -----------------------
    def test_b_missing_provenance_is_explicit_not_silent(self):
        bad = copy.deepcopy(self.too_close)
        bad.pop("provenance")

        with self.assertRaises(ConsumerError) as caught:
            validate_fixture(bad)
        self.assertEqual(caught.exception.reason_code, "PROVENANCE_MISSING")

        # The classifier must also stay explicit: non-empty reason codes, never
        # an empty/silent verdict.
        classified = classify_robustness(bad)
        self.assertTrue(classified["reason_codes"])
        self.assertIn("PROVENANCE_MISSING", classified["reason_codes"])
        self.assertEqual(classified["status"], "INSUFFICIENT_SUPPORT")

        with self.assertRaises(ConsumerError):
            build_consumer_report(bad, context=self.context, **self.docs)

    def test_b_incomplete_provenance_is_explicit_not_silent(self):
        bad = copy.deepcopy(self.too_close)
        bad["provenance"].pop("parent_issue")

        with self.assertRaises(ConsumerError) as caught:
            validate_fixture(bad)
        self.assertEqual(caught.exception.reason_code, "PROVENANCE_INCOMPLETE")
        classified = classify_robustness(bad)
        self.assertTrue(classified["reason_codes"])
        self.assertIn("PROVENANCE_INCOMPLETE", classified["reason_codes"])

    def test_b_missing_support_is_explicit_not_silent(self):
        bad = copy.deepcopy(self.too_close)
        bad["alternatives"][0].pop("support")

        with self.assertRaises(ConsumerError) as caught:
            validate_fixture(bad)
        self.assertEqual(caught.exception.reason_code, "SUPPORT_MISSING")
        self.assertIn("never be silently upgraded", caught.exception.message)

        # Fail-closed classifier: a missing support block can never be silently
        # upgraded to a supported verdict.
        classified = classify_robustness(bad)
        self.assertTrue(classified["reason_codes"])
        self.assertIn("SUPPORT_MISSING", classified["reason_codes"])
        self.assertEqual(classified["status"], "OOD_UNTESTABLE")

    def test_b_no_report_has_an_empty_reason_code_list(self):
        for name in FIXTURE_STATUSES:
            report = _report(name)
            self.assertTrue(report["reason_codes"], name)
            self.assertTrue(set(report["reason_codes"]).issubset(REASON_CODES), name)
            self.assertEqual(sorted(report["reason_codes"]), list(report["reason_codes"]))

    # --- (c) OOD => UNTESTABLE ---------------------------------------------
    def test_c_ood_fixture_is_untestable(self):
        report = _report("ood_unsupported.json")
        self.assertEqual(report["status"], "OOD_UNTESTABLE")
        self.assertIn(report["status"], STATUSES)
        self.assertTrue(report["reason_codes"])

        evidence = report["classification_evidence"]
        self.assertTrue(evidence["ood_alternatives"])
        self.assertTrue(
            set(report["reason_codes"]).issubset(
                {
                    "SUPPORT_OOD",
                    "SUPPORT_STATUS_OOD",
                    "SUPPORT_STATUS_UNKNOWN",
                    "INPUT_NOT_MAPPING",
                    "ALTERNATIVES_MISSING",
                    "ALTERNATIVE_INVALID",
                    "SUPPORT_MISSING",
                }
            )
        )

    def test_c_ood_flag_alone_is_never_downgraded(self):
        bad = copy.deepcopy(self.too_close)
        for alternative in bad["alternatives"]:
            alternative["support"] = {"status": "CONSISTENT", "tier": "VERY_HIGH", "ood": True}
        classified = classify_robustness(bad)
        self.assertEqual(classified["status"], "OOD_UNTESTABLE")
        self.assertNotIn(classified["status"], {"CONSISTENT", "TOO_CLOSE", "SENSITIVE"})

    # --- (d) too-close is preserved -----------------------------------------
    def test_d_too_close_fixture_stays_too_close(self):
        report = _report("too_close.json")
        self.assertEqual(report["status"], "TOO_CLOSE")
        self.assertNotIn(report["status"], {"CONSISTENT", "SENSITIVE"})
        self.assertTrue(report["reason_codes"])

    def test_d_too_close_is_never_requalified(self):
        # Bribe the declared support verdict and tier up to CONSISTENT/VERY_HIGH
        # and add an explicit instability block: TOO_CLOSE still wins because
        # the advantage sits inside the declared noise tolerance.
        bribed = copy.deepcopy(self.too_close)
        for alternative in bribed["alternatives"]:
            alternative["support"] = {"status": "CONSISTENT", "tier": "VERY_HIGH", "ood": False}
            alternative["paired_delta_vs_best_bb"] = 0.0
        bribed["stability"] = {"action": False, "sizing": False, "ranking": False}

        classified = classify_robustness(bribed)
        self.assertEqual(classified["status"], "TOO_CLOSE")
        self.assertNotIn(classified["status"], {"CONSISTENT", "SENSITIVE"})
        self.assertTrue(
            {"ADVANTAGE_WITHIN_TOLERANCE", "PAIRED_DELTA_WITHIN_TOLERANCE"}
            & set(classified["reason_codes"]),
            classified["reason_codes"],
        )
        self.assertIn("TOO_CLOSE", classified["evidence"]["reason_codes_by_status"])

    # --- (e) determinism ----------------------------------------------------
    def test_e_same_fixtures_same_outputs_across_two_passes(self):
        for name in sorted(FIXTURE_STATUSES):
            first = _fresh_report(name)
            second = _fresh_report(name)

            self.assertEqual(first["status"], second["status"], name)
            self.assertEqual(first["reason_codes"], second["reason_codes"], name)
            self.assertEqual(
                json.dumps(first, sort_keys=True),
                json.dumps(second, sort_keys=True),
                name,
            )
            self.assertEqual(canonical_sha256(first), canonical_sha256(second), name)
            self.assertEqual(
                first["sensitivity"]["request_sha256"],
                second["sensitivity"]["request_sha256"],
                name,
            )
            self.assertEqual(
                first["sensitivity"]["report_sha256"],
                second["sensitivity"]["report_sha256"],
                name,
            )
            self.assertEqual(len(first["sensitivity"]["request_sha256"]), 64, name)
            self.assertEqual(len(first["sensitivity"]["report_sha256"]), 64, name)

    def test_e_batch_hashes_match_the_single_run_hashes(self):
        batch = consume_batch(source_340=self.docs)
        self.assertEqual(batch["schema"], BATCH_REPORT_SCHEMA)
        for entry in batch["fixtures"]:
            report = _report(entry["fixture"])
            self.assertEqual(entry["request_sha256"], report["sensitivity"]["request_sha256"])
            self.assertEqual(entry["report_sha256"], report["sensitivity"]["report_sha256"])

    # --- (f) Model A / Model B independence ---------------------------------
    def test_f_projected_request_carries_no_forbidden_feature(self):
        request = _projected_request()
        self.assertEqual(scan_forbidden_features(request), [])

        # Mirror the consumer: the projected ``information_boundary`` block
        # enumerates the boundary flag names themselves and is asserted
        # all-false separately, so it is not a feature leak.
        scannable = {k: v for k, v in request.items() if k != "information_boundary"}
        for name, key in _iter_keys(scannable):
            lowered = key.lower()
            self.assertNotIn(lowered, FORBIDDEN_TOKENS, f"{name} leaked {key!r}")
            self.assertFalse(lowered.startswith("model_a"), f"{name} leaked {key!r}")

    def test_f_projected_request_is_structurally_action_identity_only(self):
        request = _projected_request()
        self.assertEqual(
            {frozenset(alternative) for alternative in request["alternatives"]},
            {PROJECTED_ALTERNATIVE_KEYS},
        )
        for alternative in request["alternatives"]:
            for value in alternative.values():
                self.assertNotIsInstance(value, dict)
                self.assertNotIsInstance(value, list)

    def test_f_information_boundary_is_entirely_false(self):
        request = _projected_request()
        boundary = request.get("information_boundary")
        self.assertIsInstance(boundary, dict)
        self.assertTrue(boundary)
        self.assertTrue(all(flag is False for flag in boundary.values()), boundary)
        self.assertEqual(
            independence_guard(request),
            {
                "request_has_forbidden_features": False,
                "forbidden_hits": [],
                "information_boundary_all_false": True,
            },
        )

    def test_f_every_committed_fixture_projects_a_clean_request(self):
        for name in sorted(FIXTURE_STATUSES):
            request = project_robustness_input(load_json(FIXTURES / name), context=self.context)
            self.assertEqual(scan_forbidden_features(request), [], name)
            self.assertTrue(
                all(flag is False for flag in request["information_boundary"].values()), name
            )
            self.assertEqual(_report(name)["independence"]["forbidden_hits"], [])

    # --- negative case: an injected forbidden key must be refused -----------
    def test_negative_injected_forbidden_keys_are_refused(self):
        request = _projected_request()
        injections = (
            ("ev_bb", lambda bad: bad["alternatives"][0].__setitem__("ev_bb", 1.0)),
            ("route", lambda bad: bad["alternatives"][0].__setitem__("route", "leaked")),
            (
                "support",
                lambda bad: bad["alternatives"][0].__setitem__(
                    "support", {"status": "CONSISTENT", "tier": "HIGH", "ood": False}
                ),
            ),
            (
                "uncertainty",
                lambda bad: bad["alternatives"][0].__setitem__(
                    "uncertainty", {"ci95": [0.0, 1.0], "width_bb": 1.0, "source": "x"}
                ),
            ),
            (
                "posterior_refs",
                lambda bad: bad["alternatives"][0].__setitem__("posterior_refs", ["x"]),
            ),
            ("recommended_action", lambda bad: bad.__setitem__("recommended_action", "ISO@5")),
            ("recommendation", lambda bad: bad.__setitem__("recommendation", "ISO@5")),
            ("hero_ev", lambda bad: bad.__setitem__("hero_ev", 1.0)),
            ("model_a_policy", lambda bad: bad["decision_ref"].__setitem__("model_a_policy", "x")),
        )
        for key, mutate in injections:
            with self.subTest(injected=key):
                bad = copy.deepcopy(request)
                mutate(bad)
                hits = scan_forbidden_features(bad)
                self.assertTrue(any(hit.endswith(key) for hit in hits), (key, hits))
                with self.assertRaises(ConsumerError) as caught:
                    independence_guard(bad)
                self.assertEqual(caught.exception.reason_code, "INDEPENDENCE_LEAK")

    def test_negative_truthy_boundary_flag_is_refused(self):
        request = _projected_request()
        bad = copy.deepcopy(request)
        bad["information_boundary"]["future_cards_consumed"] = True
        with self.assertRaises(ConsumerError) as caught:
            independence_guard(bad)
        self.assertEqual(caught.exception.reason_code, "INFORMATION_BOUNDARY_VIOLATION")

    def test_negative_consumer_refuses_a_leaked_projected_request(self):
        # End-to-end: even if a future projection leaked a forbidden key, the
        # consumer refuses to emit a report.
        leaked = _projected_request()
        leaked["alternatives"][0]["route"] = "leaked"
        leaked["recommended_action"] = "ISO@5"
        with mock.patch.object(consumer, "project_robustness_input", return_value=leaked):
            with self.assertRaises(ConsumerError) as caught:
                build_consumer_report(self.too_close, context=self.context, **self.docs)
        self.assertEqual(caught.exception.reason_code, "INDEPENDENCE_LEAK")


class FailClosedTests(unittest.TestCase):
    """Remaining fail-closed contract points preserved from the T5 work."""

    @classmethod
    def setUpClass(cls):
        cls.doc = load_json(FIXTURES / "too_close.json")
        cls.docs = _docs_340()
        cls.context = load_json(CONTEXT)

    def expect_validate(self, reason_code: str, mutate) -> None:
        bad = copy.deepcopy(self.doc)
        mutate(bad)
        with self.assertRaises(ConsumerError) as caught:
            validate_fixture(bad)
        self.assertEqual(caught.exception.reason_code, reason_code)
        self.assertEqual(caught.exception.to_dict()["status"], "FAIL_CLOSED")

    def test_missing_decision_fails_closed(self):
        self.expect_validate("DECISION_MISSING", lambda d: d.pop("decision"))

    def test_missing_information_boundary_fails_closed(self):
        self.expect_validate("INFORMATION_BOUNDARY_MISSING", lambda d: d.pop("information_boundary"))

    def test_unknown_field_fails_closed(self):
        self.expect_validate("INPUT_SCHEMA_VIOLATION", lambda d: d.__setitem__("extra", 1))

    def test_string_ev_is_not_accepted_as_a_number(self):
        self.expect_validate(
            "INPUT_SCHEMA_VIOLATION", lambda d: d["alternatives"][0].__setitem__("ev_bb", "1.0")
        )

    def test_provenance_consuming_real_evidence_fails_closed(self):
        self.expect_validate(
            "INPUT_SCHEMA_VIOLATION",
            lambda d: d["provenance"].__setitem__("real_issue_314_consumed", True),
        )

    def test_truthy_information_boundary_fails_closed(self):
        bad = copy.deepcopy(self.doc)
        bad["information_boundary"]["hero_ev_consumed"] = True
        with self.assertRaises(ConsumerError) as caught:
            build_consumer_report(bad, context=self.context, **self.docs)
        self.assertEqual(caught.exception.reason_code, "INFORMATION_BOUNDARY_VIOLATION")

    def test_fold_with_non_null_sizing_fails_closed_on_projection(self):
        bad = copy.deepcopy(self.doc)
        bad["alternatives"].append(
            {
                "alternative_id": "FOLD",
                "action": "FOLD",
                "sizing": 2.0,
                "route": "synthetic_robustness_route_fold",
                "source": "synthetic_monte_carlo_paired_v1",
                "ev_bb": -0.1,
                "uncertainty": {
                    "ci95": [-0.2, 0.0],
                    "width_bb": 0.2,
                    "source": "synthetic_paired_ci95_v1",
                },
                "paired_delta_vs_best_bb": -1.0,
                "support": {"status": "CONSISTENT", "tier": "HIGH", "ood": False},
                "posterior_refs": None,
            }
        )
        with self.assertRaises(ConsumerError) as caught:
            build_consumer_report(bad, context=self.context, **self.docs)
        self.assertEqual(caught.exception.reason_code, "PROJECTION_REJECTED")

    def test_public_context_mismatch_fails_closed(self):
        bad = copy.deepcopy(self.doc)
        bad["decision"]["hero_position"] = "BTN"
        with self.assertRaises(ConsumerError) as caught:
            build_consumer_report(bad, context=self.context, **self.docs)
        self.assertEqual(caught.exception.reason_code, "PROJECTION_REJECTED")


class ReportShapeTests(unittest.TestCase):
    """Report schema, identity binding and classification evidence."""

    def test_report_schema_and_status_for_every_fixture(self):
        present = {p.name for p in FIXTURES.glob("*.json")}
        self.assertTrue(set(FIXTURE_STATUSES).issubset(present), present)
        for name, expected in FIXTURE_STATUSES.items():
            report = _report(name)
            self.assertEqual(report["schema"], CONSUMER_REPORT_SCHEMA)
            self.assertEqual(
                sorted(report),
                [
                    "classification_evidence",
                    "decision_id",
                    "independence",
                    "reason_codes",
                    "schema",
                    "sensitivity",
                    "status",
                ],
            )
            self.assertEqual(report["status"], expected)
            self.assertIn(report["status"], STATUSES)
            self.assertTrue(report["decision_id"].startswith("synthetic-robustness-"))

    def test_independence_guard_flags_are_pinned_on_every_report(self):
        for name in FIXTURE_STATUSES:
            independence = _report(name)["independence"]
            self.assertIs(independence["request_has_forbidden_features"], False)
            self.assertEqual(independence["forbidden_hits"], [])
            self.assertIs(independence["information_boundary_all_false"], True)

    def test_sensitivity_block_binds_issue_340_identity_and_hashes(self):
        sensitivity = _report("robust_recommendation.json")["sensitivity"]
        self.assertEqual(
            sensitivity["issue_340_identity"]["candidate_artifact_sha256"],
            "87736a611a0000a8bc30b142a3c1db0ac2086368c6fa18441cdc211bd17f3a06",
        )
        self.assertEqual(sensitivity["issue_340_identity"]["production_effect"], "NONE")
        self.assertIs(sensitivity["issue_340_identity"]["test_consumed_by_this_harness"], False)
        self.assertEqual(len(sensitivity["request_sha256"]), 64)
        self.assertEqual(len(sensitivity["report_sha256"]), 64)

    def test_classification_evidence_is_exposed(self):
        evidence = _report("too_close.json")["classification_evidence"]
        self.assertEqual(evidence["schema"], "model-b-hero-robustness-status/v1")
        self.assertEqual(evidence["input_schema"], "hero-model-b-robustness-input/v1")
        self.assertIs(evidence["provenance_present"], True)
        self.assertIs(evidence["information_boundary_present"], True)
        self.assertEqual(evidence["boundary_violations"], [])


class SourceGuardTests(unittest.TestCase):
    """The consumer must never be wired to the forbidden real upstream runs.

    These checks are purely textual/synthetic: they never list, stat or open the
    real ``#367`` run directory, and they never reach a VALIDATION/TEST hand.
    """

    def test_consumer_module_never_hardcodes_forbidden_tokens(self):
        text = MODULE_PATH.read_text(encoding="utf-8").lower()
        for token in ("real_iso_ev", "issue367", "model_a", "hero_ev"):
            self.assertNotIn(token, text)

    def test_consumer_module_performs_no_network_io(self):
        text = MODULE_PATH.read_text(encoding="utf-8")
        for token in (
            "import requests",
            "import urllib",
            "import socket",
            "from urllib",
            "http.client",
        ):
            self.assertNotIn(token, text)

    def test_forbidden_real_run_artifacts_are_refused(self):
        fake_run = Path("/synthetic/forbidden") / f"{FORBIDDEN_RUN_MARKER}_v1"
        for tail in ("RESULT.json", "SUMMARY.json", "model/candidate.json"):
            with self.subTest(tail=tail):
                with self.assertRaises(ConsumerError) as caught:
                    assert_source_artifact_allowed(fake_run / tail)
                self.assertEqual(caught.exception.reason_code, "FORBIDDEN_UPSTREAM_ARTIFACT")

    def test_default_source_run_is_not_the_forbidden_run(self):
        normalized = str(DEFAULT_SOURCE_340_DIR).replace("\\", "/").lower()
        self.assertNotIn(FORBIDDEN_RUN_MARKER, normalized)
        self.assertEqual(
            assert_source_artifact_allowed(DEFAULT_SOURCE_340_DIR / "RESULT.json"),
            DEFAULT_SOURCE_340_DIR / "RESULT.json",
        )

    def test_no_fixture_or_provenance_touches_validation_or_test(self):
        for name in sorted(FIXTURE_STATUSES):
            fixture = load_json(FIXTURES / name)
            provenance = fixture["provenance"]
            self.assertIs(provenance["validation_consumed"], False, name)
            self.assertIs(provenance["test_consumed"], False, name)
            self.assertIs(provenance["real_issue_367_consumed"], False, name)
            self.assertIs(provenance["real_issue_314_consumed"], False, name)
            request = project_robustness_input(fixture, context=load_json(CONTEXT))
            lowered = json.dumps(request).lower()
            for token in ("validation", "test_consumed", FORBIDDEN_RUN_MARKER):
                self.assertNotIn(token, lowered, name)


class BatchModeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.docs = _docs_340()

    def test_batch_covers_every_fixture(self):
        batch = consume_batch(source_340=self.docs)
        self.assertEqual(batch["schema"], BATCH_REPORT_SCHEMA)
        self.assertEqual(batch["fixture_count"], len(batch["fixtures"]))
        by_name = {entry["fixture"]: entry["status"] for entry in batch["fixtures"]}
        for name, expected in FIXTURE_STATUSES.items():
            self.assertEqual(by_name.get(name), expected)
        self.assertEqual(sum(batch["statuses"].values()), len(batch["fixtures"]))
        self.assertEqual([entry["fixture"] for entry in batch["fixtures"]], sorted(by_name))

    def test_batch_is_deterministic(self):
        first = consume_batch(source_340=self.docs)
        second = consume_batch(source_340=self.docs)
        self.assertEqual(canonical_sha256(first), canonical_sha256(second))
        self.assertEqual(
            [entry["report_sha256"] for entry in first["fixtures"]],
            [entry["report_sha256"] for entry in second["fixtures"]],
        )

    def test_cli_batch_writes_one_report_per_fixture(self):
        with tempfile.TemporaryDirectory() as tmp:
            with redirect_stdout(io.StringIO()):
                code = main(["--batch", "--out-dir", tmp])
            self.assertEqual(code, 0)
            out = Path(tmp)
            for name in FIXTURE_STATUSES:
                report = json.loads((out / name).read_text(encoding="utf-8"))
                self.assertEqual(report["schema"], CONSUMER_REPORT_SCHEMA)
                self.assertEqual(report["status"], FIXTURE_STATUSES[name])
            summary = json.loads((out / "BATCH_SUMMARY.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["schema"], BATCH_REPORT_SCHEMA)
            self.assertNotIn("reports", summary)

    def test_cli_single_mode_writes_a_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "report.json"
            with redirect_stdout(io.StringIO()):
                code = main(
                    ["--fixture", str(FIXTURES / "robust_recommendation.json"), "--out", str(out)]
                )
            self.assertEqual(code, 0)
            report = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "CONSISTENT")
            self.assertIs(report["independence"]["information_boundary_all_false"], True)

    def test_cli_fails_closed_with_reason_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp) / "bad.json"
            bad = load_json(FIXTURES / "too_close.json")
            bad["provenance"].pop("synthetic_fixture")
            fixture.write_text(json.dumps(bad) + "\n", encoding="utf-8")
            stderr = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(stderr):
                code = main(["--fixture", str(fixture), "--out", str(Path(tmp) / "out.json")])
            self.assertEqual(code, 2)
            payload = json.loads(stderr.getvalue())
            self.assertEqual(payload["status"], "FAIL_CLOSED")
            self.assertEqual(payload["reason_code"], "PROVENANCE_INCOMPLETE")
            self.assertFalse((Path(tmp) / "out.json").exists())

    def test_cli_accepts_the_fixture_folder_as_fixture_argument(self):
        with tempfile.TemporaryDirectory() as tmp:
            with redirect_stdout(io.StringIO()):
                code = main(["--fixture", str(FIXTURES), "--out", tmp])
            self.assertEqual(code, 0)
            for name in FIXTURE_STATUSES:
                self.assertTrue((Path(tmp) / name).is_file())

    def test_cli_reports_an_unreadable_fixture(self):
        with tempfile.TemporaryDirectory() as tmp:
            stderr = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(stderr):
                code = main(
                    [
                        "--fixture",
                        str(Path(tmp) / "nope.json"),
                        "--out",
                        str(Path(tmp) / "out.json"),
                    ]
                )
            self.assertEqual(code, 2)
            self.assertEqual(json.loads(stderr.getvalue())["reason_code"], "FIXTURE_UNREADABLE")


def run_suite(verbosity: int = 2) -> bool:
    """Run the whole acceptance suite; return ``True`` when every test passes."""
    program = unittest.main(module=__name__, argv=[sys.argv[0]], exit=False, verbosity=verbosity)
    return bool(program.result.wasSuccessful())


if __name__ == "__main__":
    passed = run_suite()
    stream = sys.stdout if passed else sys.stderr
    print(
        "\n#425 backlog-hae acceptance suite: "
        + ("ALL TESTS PASSED" if passed else "FAILED (at least one test did not pass)"),
        file=stream,
    )
    raise SystemExit(0 if passed else 1)

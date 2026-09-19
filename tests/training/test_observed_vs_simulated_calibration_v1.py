#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.training.independent_profiles.evaluate_observed_vs_simulated_calibration_v1 import (  # noqa: E402
    ACTIONS,
    EXACT_CONTEXT_DIMENSIONS,
    HIERARCHY,
    _groups_by_exact_context,
    _hierarchy_groups,
    _paired_logloss_bootstrap,
    action_support_state,
    calibrate_rows,
    context_key,
    distribution_summary,
    select_validation_records,
    sizing_support_state,
    wilson95,
)


class Record:
    def __init__(self, hand_id: str):
        self.hand_id = hand_id


class FakeReference:
    def __init__(self, probabilities, sizing):
        self.probabilities = probabilities
        self.sizing_values = sizing
        self.calls = 0

    def __call__(self, row):
        self.calls += 1
        return {
            "probabilities": dict(self.probabilities),
            "sizing": distribution_summary(self.sizing_values),
        }


class FakeCandidate:
    def __init__(self, probabilities, sizing):
        self.probabilities = probabilities
        self._sizing = sizing
        self.calls = 0

    def predict(self, **row):
        self.calls += 1
        return {
            "probabilities": dict(self.probabilities),
            "sizing": distribution_summary(self._sizing),
        }

    def sizing_values(self, **row):
        return list(self._sizing)


def row(
    hand_id,
    action,
    *,
    profile=0,
    street="flop",
    pos="IP",
    pot="SRP",
    role="PFA",
    sequence="BET",
    price=0.5,
    spr=3.0,
    sizing=None,
    jam=False,
):
    out = {
        "hand_id": hand_id,
        "profile": profile,
        "street": street,
        "relative_position": pos,
        "pot_type": pot,
        "preflop_role": role,
        "sequence": sequence,
        "facing_price_to_pot": price,
        "spr": spr,
        "action": action,
        "is_jam": jam,
    }
    if sizing is not None:
        out["raise_sizing_ratio"] = sizing
    return out


class SplitSafetyTests(unittest.TestCase):
    def test_validation_only_selection_never_returns_test(self):
        records = [Record("train"), Record("validation"), Record("test")]
        split_map = {"train": "TRAIN", "validation": "VALIDATION", "test": "TEST"}
        selected = select_validation_records(records, split_fn=lambda hand_id: split_map[hand_id])
        self.assertEqual([r.hand_id for r in selected], ["validation"])

    def test_protocol_is_validation_only_and_test_fail_closed(self):
        protocol = json.loads(
            (
                ROOT
                / "training/runs/20260919_model_b_observed_vs_simulated_calibration_v1/PROTOCOL.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(protocol["split_contract"]["evaluate"], ["VALIDATION"])
        self.assertEqual(protocol["split_contract"]["forbidden"], ["TEST"])
        self.assertFalse(protocol["split_contract"]["test_consumed"])
        self.assertFalse(protocol["scientific_constraints"]["active_model_b_change_allowed"])
        self.assertEqual(protocol["scientific_constraints"]["production_effect"], "NONE")
        self.assertEqual(protocol["context_dimensions"], list(EXACT_CONTEXT_DIMENSIONS))
        self.assertEqual(protocol["declared_backoff_levels"], [list(level) for level in HIERARCHY])
        self.assertEqual(protocol["reference_row_conditioned_extra_dimensions"], ["preflop_role"])

    def test_candidate_197_forbids_model_a_recommendation_and_ev_features(self):
        source = json.loads(
            (
                ROOT / "training/runs/20260919_model_b_response_to_price_v1/model/response_to_price.json"
            ).read_text(encoding="utf-8")
        )
        forbidden = set(source["feature_contract"]["forbidden_sources"])
        self.assertTrue(
            {"model_a_ev", "model_a_policy", "model_a_recommendation"}.issubset(forbidden)
        )
        self.assertEqual(source["fit_split"], "TRAIN")
        self.assertEqual(source["production_effect"], "NONE")


class SupportTests(unittest.TestCase):
    def test_support_states(self):
        self.assertEqual(action_support_state(30, 20), "SUPPORTED")
        self.assertEqual(action_support_state(12, 6), "LOW_SUPPORT")
        self.assertEqual(action_support_state(3, 2), "INSUFFICIENT_SUPPORT")
        self.assertEqual(sizing_support_state(12, 8), "SUPPORTED")
        self.assertEqual(sizing_support_state(5, 3), "LOW_SUPPORT")
        self.assertEqual(sizing_support_state(0, 0), "NOT_APPLICABLE")

    def test_wilson_interval_contains_frequency(self):
        interval = wilson95(30, 100)
        self.assertLessEqual(interval[0], 0.30)
        self.assertGreaterEqual(interval[1], 0.30)


class ContextIsolationTests(unittest.TestCase):
    def test_context_key_contains_frozen_dimensions(self):
        r = row("h", "CALL")
        key = context_key(r)
        self.assertEqual(len(key), len(EXACT_CONTEXT_DIMENSIONS))

    def test_reference_only_preflop_role_does_not_change_issue_197_exact_context(self):
        a = row("a", "CALL", role="PFA")
        b = row("b", "CALL", role="CALLER")
        self.assertEqual(context_key(a), context_key(b))

    def test_declared_issue_197_hierarchy_is_explicit(self):
        rows = [
            row("a", "CALL", street="flop", price=0.4),
            row("b", "CALL", street="flop", price=0.8),
            row("c", "CALL", street="turn", price=0.4),
        ]
        street_groups = _hierarchy_groups(rows, ("street",))
        self.assertEqual(
            [(ctx["street"], len(group)) for ctx, group in street_groups],
            [("flop", 2), ("turn", 1)],
        )
        global_groups = _hierarchy_groups(rows, ())
        self.assertEqual(len(global_groups), 1)
        self.assertEqual(len(global_groups[0][1]), 3)

    def test_contexts_are_not_silently_pooled(self):
        rows = [
            row("a", "CALL", street="flop", price=0.4),
            row("b", "CALL", street="turn", price=0.4),
            row("c", "CALL", street="flop", price=0.8),
        ]
        groups = _groups_by_exact_context(rows)
        self.assertEqual(len(groups), 3)
        self.assertEqual(sum(len(group) for _, group in groups), len(rows))


class CalibrationTests(unittest.TestCase):
    def _calibrate(self, rows, ref_probs, cand_probs, ref_sizes=None, cand_sizes=None):
        ref = FakeReference(ref_probs, ref_sizes or [0.75, 1.0, 1.5])
        cand = FakeCandidate(cand_probs, cand_sizes or [0.75, 1.0, 1.5])
        with patch(
            "tools.training.independent_profiles.evaluate_observed_vs_simulated_calibration_v1._reference_sizing_values",
            side_effect=lambda reference, observation: list(reference.sizing_values),
        ):
            report = calibrate_rows(
                rows,
                reference=ref,
                candidate=cand,
                bootstrap_samples=100,
                label="fixture",
            )
        return report, ref, cand

    def test_fold_call_raise_frequencies_and_same_row_set(self):
        rows = []
        actions = ["FOLD", "CALL", "RAISE"] * 10
        for i, action in enumerate(actions):
            rows.append(
                row(
                    f"h{i}",
                    action,
                    sizing=1.0 if action == "RAISE" else None,
                )
            )
        report, ref, cand = self._calibrate(
            rows,
            {"FOLD": 0.30, "CALL": 0.40, "RAISE": 0.30},
            {"FOLD": 1 / 3, "CALL": 1 / 3, "RAISE": 1 / 3},
        )
        self.assertEqual(report["support_tier"], "SUPPORTED")
        self.assertEqual(set(report["actions"]), set(ACTIONS))
        for action in ACTIONS:
            self.assertEqual(report["actions"][action]["observed_count"], 10)
        self.assertEqual(ref.calls, len(rows))
        self.assertEqual(cand.calls, len(rows))

    def test_sizing_log2_error_and_distribution_are_separate(self):
        rows = [
            row(f"h{i}", "RAISE", sizing=1.0 if i % 2 == 0 else 2.0)
            for i in range(20)
        ]
        report, _, _ = self._calibrate(
            rows,
            {"FOLD": 0.2, "CALL": 0.3, "RAISE": 0.5},
            {"FOLD": 0.2, "CALL": 0.3, "RAISE": 0.5},
            ref_sizes=[0.5, 1.0],
            cand_sizes=[1.0, 2.0],
        )
        sizing = report["sizing_calibration"]
        self.assertEqual(sizing["support_tier"], "SUPPORTED")
        self.assertEqual(sizing["observed_raise_count"], 20)
        self.assertIsNotNone(sizing["reference_log2_error"]["median_absolute_log2_error"])
        self.assertIsNotNone(sizing["candidate_log2_error"]["median_absolute_log2_error"])
        self.assertGreater(sizing["simulated_candidate_distribution"]["n"], 0)

    def test_jam_overbet_and_tail_calibration(self):
        rows = [
            row("j1", "RAISE", sizing=3.0, spr=3.0, jam=True),
            row("o1", "RAISE", sizing=1.5, spr=5.0),
            row("c1", "CALL", spr=5.0),
        ] * 10
        # Keep hand ids distinct enough for support.
        rows = [dict(r, hand_id=f"{r['hand_id']}-{i}") for i, r in enumerate(rows)]
        report, _, _ = self._calibrate(
            rows,
            {"FOLD": 0.2, "CALL": 0.3, "RAISE": 0.5},
            {"FOLD": 0.2, "CALL": 0.3, "RAISE": 0.5},
            ref_sizes=[0.5, 1.0],
            cand_sizes=[1.5, 3.0],
        )
        tails = report["aggressive_tails"]
        self.assertGreater(tails["observed"]["jam_count"], 0)
        self.assertGreater(tails["observed"]["overbet_count"], 0)
        self.assertGreater(tails["observed"]["tail_count"], 0)
        self.assertIn("jam_frequency_absolute_error", tails["candidate"])
        self.assertIn("overbet_frequency_absolute_error", tails["candidate"])

    def test_low_support_does_not_claim_interpretability(self):
        rows = [row(f"h{i}", "CALL") for i in range(6)]
        report, _, _ = self._calibrate(
            rows,
            {"FOLD": 0.2, "CALL": 0.6, "RAISE": 0.2},
            {"FOLD": 0.2, "CALL": 0.6, "RAISE": 0.2},
        )
        self.assertEqual(report["support_tier"], "INSUFFICIENT_SUPPORT")
        self.assertFalse(report["interpretable"])
        self.assertEqual(report["comparison"], "INSUFFICIENT_SUPPORT")

    def test_high_support_can_report_candidate_improvement(self):
        rows = [row(f"h{i}", "FOLD") for i in range(40)]
        report, _, _ = self._calibrate(
            rows,
            {"FOLD": 0.4, "CALL": 0.3, "RAISE": 0.3},
            {"FOLD": 0.9, "CALL": 0.05, "RAISE": 0.05},
        )
        self.assertEqual(report["support_tier"], "SUPPORTED")
        self.assertEqual(report["comparison"], "CANDIDATE_IMPROVES")

    def test_probability_metrics_include_brier_logloss_and_ece(self):
        rows = [row(f"h{i}", "CALL") for i in range(30)]
        report, _, _ = self._calibrate(
            rows,
            {"FOLD": 0.2, "CALL": 0.6, "RAISE": 0.2},
            {"FOLD": 0.1, "CALL": 0.8, "RAISE": 0.1},
        )
        for model in ("reference", "candidate"):
            metrics = report["probability_calibration"][model]
            self.assertIsNotNone(metrics["log_loss"])
            self.assertIsNotNone(metrics["brier"])
            self.assertIsNotNone(metrics["ece_confidence"])


class DeterminismTests(unittest.TestCase):
    def test_cluster_bootstrap_is_deterministic(self):
        rows = [
            {"hand_id": f"h{i // 2}", "logloss_delta": -0.1 if i % 2 else -0.2}
            for i in range(40)
        ]
        a = _paired_logloss_bootstrap(rows, samples=200, seed_label="same")
        b = _paired_logloss_bootstrap(rows, samples=200, seed_label="same")
        self.assertEqual(a, b)

    def test_context_partition_source_counts_are_coherent(self):
        rows = [
            row(f"h{i}", "CALL", street="flop" if i < 10 else "turn")
            for i in range(20)
        ]
        groups = _groups_by_exact_context(rows)
        self.assertEqual(sum(len(group) for _, group in groups), 20)


if __name__ == "__main__":
    unittest.main()

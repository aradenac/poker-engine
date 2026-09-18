#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.simulation.model_b_price_diagnostics import (  # noqa: E402
    counterfactual_response_report,
    evaluate_validation,
    plausible_action_environments,
    summarize_strategy_sensitivity,
)
from tools.simulation.model_b_price_response import (  # noqa: E402
    ResponseToPriceModel,
    build_response_artifact,
    price_bucket,
    spr_bucket,
)


def row(
    *,
    price,
    spr=3.0,
    action="CALL",
    sequence="BET",
    profile=1,
    sizing=None,
    hand_id=None,
    is_jam=False,
):
    out = {
        "profile": profile,
        "street": "flop",
        "relative_position": "OOP",
        "pot_type": "SRP",
        "sequence": sequence,
        "facing_price_to_pot": price,
        "spr": spr,
        "action": action,
        "hand_id": hand_id,
        "is_jam": is_jam,
    }
    if sizing is not None:
        out["raise_sizing_ratio"] = sizing
    return out


class PriceResponseTests(unittest.TestCase):
    def test_bucket_boundaries(self):
        self.assertEqual(price_bucket(0.25), "P00_25")
        self.assertEqual(price_bucket(0.50), "P25_50")
        self.assertEqual(price_bucket(2.51), "P250_PLUS")
        self.assertEqual(spr_bucket(1.0), "SPR00_1")
        self.assertEqual(spr_bucket(8.1), "SPR8_PLUS")

    def test_model_preserves_non_monotonic_empirical_response(self):
        observations = []
        observations += [row(price=0.4, action="FOLD") for _ in range(8)]
        observations += [row(price=0.4, action="CALL") for _ in range(2)]
        observations += [row(price=0.9, action="FOLD") for _ in range(2)]
        observations += [row(price=0.9, action="CALL") for _ in range(8)]
        model = ResponseToPriceModel(
            build_response_artifact(observations, min_support=5)
        )
        low = model.predict(**row(price=0.4))
        high = model.predict(**row(price=0.9))
        self.assertGreater(
            low["probabilities"]["FOLD"],
            high["probabilities"]["FOLD"],
        )
        self.assertEqual(
            model.document["feature_contract"]["price_monotonicity_assumption"],
            "NONE",
        )

    def test_sequence_spr_and_profile_are_in_full_context_and_backoff_is_explicit(self):
        observations = []
        observations += [
            row(
                price=0.6,
                spr=1.5,
                sequence="XR",
                profile=1,
                action="FOLD",
            )
            for _ in range(6)
        ]
        observations += [
            row(
                price=0.6,
                spr=1.5,
                sequence="XR",
                profile=1,
                action="CALL",
            )
            for _ in range(2)
        ]
        observations += [
            row(
                price=0.6,
                spr=6.0,
                sequence="BET",
                profile=2,
                action="CALL",
            )
            for _ in range(8)
        ]
        model = ResponseToPriceModel(
            build_response_artifact(observations, min_support=5)
        )
        exact = model.predict(
            **row(
                price=0.6,
                spr=1.5,
                sequence="XR",
                profile=1,
            )
        )
        sparse = model.predict(
            **row(
                price=0.6,
                spr=1.5,
                sequence="XR",
                profile=99,
            )
        )
        self.assertEqual(exact["identifiability"], "LOCAL_SUPPORTED")
        self.assertTrue(sparse["selection"]["used_backoff"])
        self.assertIn(
            sparse["identifiability"],
            {"BACKOFF_SUPPORTED", "LOW_SUPPORT"},
        )

    def test_uncertainty_and_raise_sizing_are_machine_readable(self):
        observations = [
            row(
                price=1.7,
                action="RAISE",
                sizing=2.0 + i * 0.1,
            )
            for i in range(10)
        ]
        model = ResponseToPriceModel(
            build_response_artifact(observations, min_support=5)
        )
        pred = model.predict(**row(price=1.7))
        self.assertEqual(pred["sizing"]["n"], 10)
        self.assertIsNotNone(pred["sizing"]["p99"])
        low, high = pred["uncertainty"]["FOLD"]["approx_95"]
        self.assertLessEqual(low, pred["probabilities"]["FOLD"])
        self.assertGreaterEqual(high, pred["probabilities"]["FOLD"])


class DiagnosticsTests(unittest.TestCase):
    def setUp(self):
        observations = []
        for i in range(30):
            observations.append(
                row(
                    price=0.4,
                    action="CALL",
                    hand_id=f"t{i}",
                )
            )
        for i in range(30):
            observations.append(
                row(
                    price=1.8,
                    action="FOLD",
                    hand_id=f"u{i}",
                    is_jam=i < 5,
                )
            )
        self.model = ResponseToPriceModel(
            build_response_artifact(observations, min_support=5)
        )

    def candidate(self, validation_row):
        return self.model.predict(**validation_row)

    @staticmethod
    def reference(validation_row):
        del validation_row
        return {
            "probabilities": {
                "FOLD": 1 / 3,
                "CALL": 1 / 3,
                "RAISE": 1 / 3,
            },
            "sizing": {"median": 1.0},
        }

    def test_validation_is_paired_and_has_tail_metrics(self):
        validation = [
            row(
                price=0.4,
                action="CALL",
                hand_id="a",
            ),
            row(
                price=0.4,
                action="CALL",
                hand_id="b",
            ),
            row(
                price=1.8,
                action="FOLD",
                hand_id="c",
                is_jam=True,
            ),
            row(
                price=1.8,
                action="FOLD",
                hand_id="d",
            ),
        ]
        report = evaluate_validation(
            validation,
            candidate_predict=self.candidate,
            reference_predict=self.reference,
            bootstrap_samples=200,
        )
        self.assertLess(
            report["paired_action_log_loss"][
                "observed_candidate_minus_reference_log_loss"
            ],
            0,
        )
        self.assertGreater(
            report["tail_diagnostics"]["candidate_actions"]["n"],
            0,
        )
        self.assertFalse(report["test_consumed"])
        self.assertEqual(report["promotion_effect"], "NONE")

    def test_counterfactual_changes_only_price_and_does_not_gate_monotonicity(self):
        context = row(price=0.4)
        context.pop("facing_price_to_pot")
        report = counterfactual_response_report(
            [context],
            price_points=[0.4, 1.8],
            predict=lambda probe: self.model.predict(**probe),
        )
        curve = report["contexts"][0]
        self.assertGreater(curve["fold_spread"], 0.1)
        self.assertFalse(curve["monotonicity_is_gate"])

    def test_plausible_environments_are_unweighted(self):
        prediction = self.model.predict(**row(price=1.8))
        environments = plausible_action_environments(prediction)
        self.assertEqual(
            [env["environment_id"] for env in environments],
            ["fold-low", "nominal", "fold-high"],
        )
        self.assertTrue(all(env["weight"] is None for env in environments))
        for env in environments:
            self.assertAlmostEqual(
                sum(env["probabilities"].values()),
                1.0,
                places=12,
            )

    def test_strategy_sensitivity_separates_action_sizing_and_ev(self):
        result = summarize_strategy_sensitivity(
            [
                {
                    "environment_id": "nominal",
                    "action": "RAISE",
                    "sizing": 1.5,
                    "ev_bb": 2.0,
                },
                {
                    "environment_id": "fold-low",
                    "action": "CALL",
                    "sizing": None,
                    "ev_bb": 1.6,
                },
                {
                    "environment_id": "fold-high",
                    "action": "RAISE",
                    "sizing": 2.0,
                    "ev_bb": 2.2,
                },
            ]
        )
        self.assertFalse(result["action_stable"])
        self.assertFalse(result["sizing_stable"])
        self.assertAlmostEqual(result["max_regret_bb"], 0.6)
        self.assertFalse(result["environments_weighted"])


if __name__ == "__main__":
    unittest.main()

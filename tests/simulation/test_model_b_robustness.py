#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.simulation.model_b_robustness import (  # noqa: E402
    compact_robustness_summary,
    environment_declarations,
    evaluate_robustness,
    response_to_price_context_environment_sets,
)


def envs():
    return [
        {"environment_id": "nom", "role": "nominal"},
        {"environment_id": "low", "role": "lower_aggression"},
        {"environment_id": "high", "role": "higher_aggression"},
    ]


def evaluation(env, alt, action, sizing, ev, *, ci=None, supported=True, shove=False, overbet=False):
    return {
        "environment_id": env,
        "alternative_id": alt,
        "action": action,
        "sizing": sizing,
        "ev_bb": ev,
        "mc_ci95": ci,
        "environment_supported": supported,
        "is_shove": shove,
        "is_overbet": overbet,
    }


class EnvironmentContractTests(unittest.TestCase):
    def test_existing_sensitivity_schema_is_accepted_without_weights(self):
        document = {
            "schema": "poker-model-b-sensitivity-set/v1",
            "environments": [
                {"environment_id": "n", "role": "nominal", "raise_odds_multiplier": 1.0},
                {"environment_id": "l", "role": "lower_aggression", "raise_odds_multiplier": 0.9},
                {"environment_id": "h", "role": "higher_aggression", "raise_odds_multiplier": 1.1},
            ],
        }
        rows = environment_declarations(document)
        self.assertEqual(
            [row["role"] for row in rows],
            ["nominal", "lower_aggression", "higher_aggression"],
        )

    def test_issue_197_contextual_environments_are_accepted_without_weights(self):
        document = {
            "schema": "model-b-response-to-price-plausible-environments/v1",
            "environments_weighted": False,
            "contexts": [{
                "context_index": 3,
                "identifiability": "LOCAL_SUPPORTED",
                "context": {
                    "street": "turn",
                    "profile": 0,
                    "relative_position": "IP",
                    "pot_type": "LIMPED",
                    "sequence": "BET",
                    "spr": 21.5,
                    "representative_price_to_pot": 0.2857,
                    "validation_support": 47,
                },
                "environments": [
                    {
                        "environment_id": "fold-low",
                        "probabilities": {"FOLD": 0.30, "CALL": 0.60, "RAISE": 0.10},
                        "weight": None,
                    },
                    {
                        "environment_id": "nominal",
                        "probabilities": {"FOLD": 0.40, "CALL": 0.50, "RAISE": 0.10},
                        "weight": None,
                    },
                    {
                        "environment_id": "fold-high",
                        "probabilities": {"FOLD": 0.50, "CALL": 0.40, "RAISE": 0.10},
                        "weight": None,
                    },
                ],
            }],
        }
        contexts = response_to_price_context_environment_sets(document)
        self.assertEqual(len(contexts), 1)
        self.assertTrue(contexts[0]["environment_supported"])
        self.assertEqual(contexts[0]["validation_support"], 47)
        self.assertEqual(
            [row["role"] for row in contexts[0]["environments"]],
            ["lower_fold_response_stress", "nominal", "higher_fold_response_stress"],
        )
        self.assertTrue(all(row["environment_supported"] for row in contexts[0]["environments"]))

    def test_issue_197_contextual_environment_weight_is_fail_closed(self):
        document = {
            "schema": "model-b-response-to-price-plausible-environments/v1",
            "environments_weighted": False,
            "contexts": [{
                "context_index": 0,
                "identifiability": "LOCAL_SUPPORTED",
                "context": {"validation_support": 20},
                "environments": [
                    {
                        "environment_id": "nominal",
                        "probabilities": {"FOLD": 0.4, "CALL": 0.5, "RAISE": 0.1},
                        "weight": 0.8,
                    },
                    {
                        "environment_id": "fold-high",
                        "probabilities": {"FOLD": 0.5, "CALL": 0.4, "RAISE": 0.1},
                        "weight": None,
                    },
                ],
            }],
        }
        with self.assertRaisesRegex(ValueError, "forbidden weight"):
            response_to_price_context_environment_sets(document)

    def test_issue_197_contextual_probabilities_are_fail_closed(self):
        document = {
            "schema": "model-b-response-to-price-plausible-environments/v1",
            "environments_weighted": False,
            "contexts": [{
                "context_index": 0,
                "identifiability": "LOCAL_SUPPORTED",
                "context": {"validation_support": 20},
                "environments": [
                    {
                        "environment_id": "nominal",
                        "probabilities": {"FOLD": 0.4, "CALL": 0.5, "RAISE": 0.2},
                        "weight": None,
                    },
                    {
                        "environment_id": "fold-high",
                        "probabilities": {"FOLD": 0.5, "CALL": 0.4, "RAISE": 0.1},
                        "weight": None,
                    },
                ],
            }],
        }
        with self.assertRaisesRegex(ValueError, "do not sum to 1"):
            response_to_price_context_environment_sets(document)

    def test_issue_197_low_support_context_forces_insufficient_support(self):
        document = {
            "schema": "model-b-response-to-price-plausible-environments/v1",
            "environments_weighted": False,
            "contexts": [{
                "context_index": 0,
                "identifiability": "LOW_SUPPORT",
                "context": {"validation_support": 1},
                "environments": [
                    {
                        "environment_id": "fold-low",
                        "probabilities": {"FOLD": 0.3, "CALL": 0.6, "RAISE": 0.1},
                        "weight": None,
                    },
                    {
                        "environment_id": "nominal",
                        "probabilities": {"FOLD": 0.4, "CALL": 0.5, "RAISE": 0.1},
                        "weight": None,
                    },
                    {
                        "environment_id": "fold-high",
                        "probabilities": {"FOLD": 0.5, "CALL": 0.4, "RAISE": 0.1},
                        "weight": None,
                    },
                ],
            }],
        }
        env = response_to_price_context_environment_sets(document)[0]["environments"]
        rows = []
        for item in env:
            env_id = item["environment_id"]
            rows += [
                evaluation(env_id, "raise", "RAISE", 1.0, 2.0),
                evaluation(env_id, "call", "CALL", None, 1.0),
            ]
        report = evaluate_robustness(
            decision_id="low-support",
            environments=env,
            evaluations=rows,
        )
        self.assertEqual(report["classification"], "INSUFFICIENTLY_SUPPORTED")
        self.assertFalse(report["support"]["all_environments_supported"])

    def test_environment_probability_weight_is_rejected(self):
        document = {
            "schema": "model-b-robustness-environment-set/v1",
            "environments": [
                {"environment_id": "n", "role": "nominal", "weight": 0.8},
                {"environment_id": "x", "role": "stress"},
            ],
        }
        with self.assertRaisesRegex(ValueError, "forbidden weight"):
            environment_declarations(document)


class RobustnessTests(unittest.TestCase):
    def test_robust_case_keeps_action_sizing_and_mc_separate(self):
        rows = []
        values = {
            "nom": (2.00, 1.60),
            "low": (1.95, 1.55),
            "high": (1.90, 1.50),
        }
        for env, (raise_ev, call_ev) in values.items():
            rows += [
                evaluation(
                    env,
                    "raise150",
                    "RAISE",
                    1.5,
                    raise_ev,
                    ci=[raise_ev - 0.1, raise_ev + 0.1],
                ),
                evaluation(
                    env,
                    "call",
                    "CALL",
                    None,
                    call_ev,
                    ci=[call_ev - 0.1, call_ev + 0.1],
                ),
            ]
        report = evaluate_robustness(
            decision_id="d1",
            environments=envs(),
            evaluations=rows,
        )
        self.assertEqual(report["classification"], "ROBUST")
        self.assertTrue(report["stability"]["action_stable"])
        self.assertTrue(report["stability"]["sizing_stable"])
        self.assertEqual(
            report["nominal_recommendation"]["mc_uncertainty"]["ci95"],
            [1.9, 2.1],
        )
        self.assertEqual(
            report["environment_uncertainty"]["nominal_recommendation_ev_span_bb"],
            [1.9, 2.0],
        )
        self.assertFalse(report["environment_uncertainty"]["environments_weighted"])

    def test_sensitive_case_when_best_action_changes(self):
        rows = [
            evaluation("nom", "jam", "RAISE", 4.0, 2.0, shove=True),
            evaluation("nom", "call", "CALL", None, 1.7),
            evaluation("low", "jam", "RAISE", 4.0, 1.4, shove=True),
            evaluation("low", "call", "CALL", None, 1.8),
            evaluation("high", "jam", "RAISE", 4.0, 2.2, shove=True),
            evaluation("high", "call", "CALL", None, 1.6),
        ]
        report = evaluate_robustness(
            decision_id="d2",
            environments=envs(),
            evaluations=rows,
        )
        self.assertEqual(report["classification"], "SENSITIVE")
        self.assertFalse(report["stability"]["action_stable"])
        self.assertAlmostEqual(
            report["environment_uncertainty"]["max_regret_bb"],
            0.4,
        )
        self.assertTrue(report["aggressive_fragility"]["advantage_disappears"])
        self.assertEqual(
            report["aggressive_fragility"]["affected_environments"],
            ["low"],
        )

    def test_sensitive_case_when_only_sizing_changes(self):
        rows = [
            evaluation("nom", "r100", "RAISE", 1.0, 2.0),
            evaluation("nom", "r150", "RAISE", 1.5, 1.9),
            evaluation("low", "r100", "RAISE", 1.0, 1.7),
            evaluation("low", "r150", "RAISE", 1.5, 1.9),
            evaluation("high", "r100", "RAISE", 1.0, 2.1),
            evaluation("high", "r150", "RAISE", 1.5, 2.0),
        ]
        report = evaluate_robustness(
            decision_id="d3",
            environments=envs(),
            evaluations=rows,
        )
        self.assertEqual(report["classification"], "SENSITIVE")
        self.assertTrue(report["stability"]["action_stable"])
        self.assertFalse(report["stability"]["sizing_stable"])

    def test_unsupported_environment_dominates_classification(self):
        rows = []
        for env in ("nom", "low", "high"):
            supported = env != "high"
            rows += [
                evaluation(
                    env,
                    "raise",
                    "RAISE",
                    1.0,
                    2.0,
                    supported=supported,
                ),
                evaluation(
                    env,
                    "call",
                    "CALL",
                    None,
                    1.0,
                    supported=supported,
                ),
            ]
        report = evaluate_robustness(
            decision_id="d4",
            environments=envs(),
            evaluations=rows,
        )
        self.assertEqual(report["classification"], "INSUFFICIENTLY_SUPPORTED")
        self.assertFalse(report["support"]["all_environments_supported"])

    def test_ranking_is_reported_per_environment(self):
        rows = [
            evaluation("nom", "a", "CALL", None, 3.0),
            evaluation("nom", "b", "RAISE", 1.0, 2.0),
            evaluation("low", "a", "CALL", None, 2.0),
            evaluation("low", "b", "RAISE", 1.0, 3.0),
            evaluation("high", "a", "CALL", None, 3.0),
            evaluation("high", "b", "RAISE", 1.0, 2.0),
        ]
        report = evaluate_robustness(
            decision_id="d5",
            environments=envs(),
            evaluations=rows,
        )
        self.assertFalse(report["stability"]["ranking_stable"])
        by_id = {row["environment_id"]: row for row in report["environments"]}
        self.assertEqual(by_id["nom"]["best"]["ranking"], ["a", "b"])
        self.assertEqual(by_id["low"]["best"]["ranking"], ["b", "a"])

    def test_compact_summary_hides_full_environment_detail(self):
        rows = []
        for env in ("nom", "low", "high"):
            rows += [
                evaluation(
                    env,
                    "raise",
                    "RAISE",
                    1.0,
                    2.0,
                    ci=[1.8, 2.2],
                ),
                evaluation(
                    env,
                    "call",
                    "CALL",
                    None,
                    1.0,
                    ci=[0.8, 1.2],
                ),
            ]
        report = evaluate_robustness(
            decision_id="d6",
            environments=envs(),
            evaluations=rows,
        )
        summary = compact_robustness_summary(report)
        self.assertEqual(summary["status"], "robust")
        self.assertNotIn("environments", summary)
        self.assertEqual(summary["nominal"]["mc_ci95"], [1.8, 2.2])
        self.assertFalse(summary["model_environment"]["weighted"])
        self.assertTrue(summary["detail_available"])


if __name__ == "__main__":
    unittest.main()

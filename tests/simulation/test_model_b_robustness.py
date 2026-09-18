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


    def test_repository_issue_197_environment_artifact_is_accepted_context_by_context(self):
        source = ROOT / "training/runs/20260919_model_b_response_to_price_v1/plausible_environments.json"
        document = __import__("json").loads(source.read_text(encoding="utf-8"))
        contexts = response_to_price_context_environment_sets(document)
        self.assertEqual(len(contexts), 12)
        self.assertTrue(all(context["environment_supported"] for context in contexts))
        self.assertTrue(all(context["validation_support"] > 0 for context in contexts))
        for context in contexts:
            environments = context["environments"]
            self.assertEqual(len(environments), 3)
            self.assertEqual(sum(row["role"] == "nominal" for row in environments), 1)
            self.assertTrue(all(row["environment_supported"] for row in environments))

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


class RequiredRobustnessCompletionTests(unittest.TestCase):
    def test_missing_environment_is_insufficiently_supported(self):
        rows = [
            evaluation("nom", "raise", "RAISE", 1.0, 2.0, ci=[1.9, 2.1]),
            evaluation("nom", "call", "CALL", None, 1.0, ci=[0.9, 1.1]),
            evaluation("low", "raise", "RAISE", 1.0, 1.9, ci=[1.8, 2.0]),
            evaluation("low", "call", "CALL", None, 1.0, ci=[0.9, 1.1]),
        ]
        report = evaluate_robustness(
            decision_id="missing-env",
            environments=envs(),
            evaluations=rows,
        )
        self.assertEqual(report["classification"], "INSUFFICIENTLY_SUPPORTED")
        self.assertFalse(report["environment_uncertainty"]["comparable"])
        self.assertEqual(report["environment_uncertainty"]["missing_environment_ids"], ["high"])
        self.assertIsNone(report["stability"]["action_stable"])
        self.assertIsNone(report["environment_uncertainty"]["max_regret_bb"])

    def test_missing_alternative_is_insufficiently_supported(self):
        rows = [
            evaluation("nom", "raise", "RAISE", 1.0, 2.0),
            evaluation("nom", "call", "CALL", None, 1.5),
            evaluation("low", "raise", "RAISE", 1.0, 1.9),
            evaluation("low", "call", "CALL", None, 1.4),
            evaluation("high", "raise", "RAISE", 1.0, 1.8),
        ]
        report = evaluate_robustness(
            decision_id="missing-alt",
            environments=envs(),
            evaluations=rows,
        )
        self.assertEqual(report["classification"], "INSUFFICIENTLY_SUPPORTED")
        self.assertEqual(
            report["environment_uncertainty"]["missing_alternatives_by_environment"],
            {"high": ["call"]},
        )

    def test_shove_fragility_reports_nominal_advantage_and_worst_regret(self):
        rows = [
            evaluation("nom", "jam", "RAISE", 4.0, 2.0, ci=[1.98, 2.02], shove=True),
            evaluation("nom", "call", "CALL", None, 1.7, ci=[1.68, 1.72]),
            evaluation("low", "jam", "RAISE", 4.0, 1.4, ci=[1.38, 1.42], shove=True),
            evaluation("low", "call", "CALL", None, 1.8, ci=[1.78, 1.82]),
            evaluation("high", "jam", "RAISE", 4.0, 2.2, ci=[2.18, 2.22], shove=True),
            evaluation("high", "call", "CALL", None, 1.6, ci=[1.58, 1.62]),
        ]
        report = evaluate_robustness(
            decision_id="fragile-jam",
            environments=envs(),
            evaluations=rows,
        )
        diagnostic = report["diagnostics"]["shove_fragility"]
        self.assertEqual(report["classification"], "SENSITIVE")
        self.assertTrue(diagnostic["applicable"])
        self.assertTrue(diagnostic["fragile"])
        self.assertEqual(diagnostic["affected_environments"], ["low"])
        self.assertAlmostEqual(diagnostic["nominal_advantage_bb"], 0.3)
        self.assertEqual(
            diagnostic["worst_environment_regret"]["environment_id"],
            "low",
        )
        self.assertAlmostEqual(
            diagnostic["worst_environment_regret"]["regret_bb"],
            0.4,
        )

    def test_overbet_fragility_is_reported_separately(self):
        rows = [
            evaluation("nom", "overbet", "RAISE", 1.5, 2.0, overbet=True),
            evaluation("nom", "small", "RAISE", 0.75, 1.85),
            evaluation("low", "overbet", "RAISE", 1.5, 1.6, overbet=True),
            evaluation("low", "small", "RAISE", 0.75, 1.9),
            evaluation("high", "overbet", "RAISE", 1.5, 2.1, overbet=True),
            evaluation("high", "small", "RAISE", 0.75, 1.8),
        ]
        report = evaluate_robustness(
            decision_id="fragile-overbet",
            environments=envs(),
            evaluations=rows,
        )
        diagnostic = report["diagnostics"]["overbet_fragility"]
        self.assertTrue(diagnostic["applicable"])
        self.assertTrue(diagnostic["fragile"])
        self.assertEqual(diagnostic["affected_environments"], ["low"])
        self.assertTrue(report["stability"]["action_stable"])
        self.assertFalse(report["stability"]["sizing_stable"])

    def test_high_mc_uncertainty_can_coexist_with_low_model_uncertainty(self):
        rows = []
        for env, raise_ev in (("nom", 2.00), ("low", 1.98), ("high", 1.97)):
            rows += [
                evaluation(env, "raise", "RAISE", 1.0, raise_ev, ci=[0.0, 4.0]),
                evaluation(env, "call", "CALL", None, 1.0, ci=[-1.0, 3.0]),
            ]
        report = evaluate_robustness(
            decision_id="wide-mc-low-model",
            environments=envs(),
            evaluations=rows,
        )
        self.assertEqual(report["classification"], "ROBUST")
        self.assertAlmostEqual(
            report["nominal_recommendation"]["mc_uncertainty"]["ci95_width_bb"],
            4.0,
        )
        self.assertLess(
            report["environment_uncertainty"]["nominal_recommendation_ev_range_width_bb"],
            0.05,
        )
        nominal_env = next(
            row for row in report["environments"] if row["environment_id"] == "nom"
        )
        self.assertTrue(
            all("mc_uncertainty" in alt for alt in nominal_env["alternatives"])
        )

    def test_high_model_uncertainty_can_coexist_with_low_mc_uncertainty(self):
        rows = [
            evaluation("nom", "raise", "RAISE", 1.0, 2.0, ci=[1.99, 2.01]),
            evaluation("nom", "call", "CALL", None, 1.8, ci=[1.79, 1.81]),
            evaluation("low", "raise", "RAISE", 1.0, 1.0, ci=[0.99, 1.01]),
            evaluation("low", "call", "CALL", None, 2.0, ci=[1.99, 2.01]),
            evaluation("high", "raise", "RAISE", 1.0, 2.2, ci=[2.19, 2.21]),
            evaluation("high", "call", "CALL", None, 1.7, ci=[1.69, 1.71]),
        ]
        report = evaluate_robustness(
            decision_id="low-mc-high-model",
            environments=envs(),
            evaluations=rows,
        )
        self.assertEqual(report["classification"], "SENSITIVE")
        self.assertLess(
            report["nominal_recommendation"]["mc_uncertainty"]["ci95_width_bb"],
            0.03,
        )
        self.assertGreater(
            report["environment_uncertainty"]["nominal_recommendation_ev_range_width_bb"],
            1.0,
        )
        self.assertFalse(report["stability"]["action_stable"])

    def test_compact_summary_contains_only_decision_level_robustness_fields(self):
        rows = []
        for env in ("nom", "low", "high"):
            rows += [
                evaluation(env, "raise", "RAISE", 1.0, 2.0, ci=[1.9, 2.1]),
                evaluation(env, "call", "CALL", None, 1.0, ci=[0.9, 1.1]),
            ]
        report = evaluate_robustness(
            decision_id="summary",
            environments=envs(),
            evaluations=rows,
        )
        summary = compact_robustness_summary(report)
        self.assertEqual(summary["status"], "robust")
        self.assertEqual(summary["nominal"]["action"], "RAISE")
        self.assertIn("advantage_bb", summary["nominal"])
        self.assertTrue(summary["model_environment"]["comparable"])
        self.assertIn("worst_environment_regret", summary["model_environment"])
        self.assertNotIn("environments", summary)
        self.assertIn("shove_fragility", summary)
        self.assertIn("overbet_fragility", summary)

    def test_contexts_with_same_environment_ids_are_never_pooled(self):
        def context(index, fold):
            return {
                "context_index": index,
                "identifiability": "LOCAL_SUPPORTED",
                "context": {"validation_support": 25 + index, "street": "flop"},
                "environments": [
                    {
                        "environment_id": "fold-low",
                        "probabilities": {"FOLD": fold - 0.1, "CALL": 1.0 - fold, "RAISE": 0.1},
                        "weight": None,
                    },
                    {
                        "environment_id": "nominal",
                        "probabilities": {"FOLD": fold, "CALL": 0.9 - fold, "RAISE": 0.1},
                        "weight": None,
                    },
                    {
                        "environment_id": "fold-high",
                        "probabilities": {"FOLD": fold + 0.1, "CALL": 0.8 - fold, "RAISE": 0.1},
                        "weight": None,
                    },
                ],
            }
        document = {
            "schema": "model-b-response-to-price-plausible-environments/v1",
            "environments_weighted": False,
            "contexts": [context(0, 0.4), context(1, 0.6)],
        }
        contexts = response_to_price_context_environment_sets(document)
        self.assertEqual(
            [row["context_id"] for row in contexts],
            ["response-to-price-context-0", "response-to-price-context-1"],
        )
        self.assertNotEqual(
            contexts[0]["environments"][1]["metadata"]["response_probabilities"],
            contexts[1]["environments"][1]["metadata"]["response_probabilities"],
        )

    def test_undeclared_environment_evaluation_is_rejected(self):
        rows = [
            evaluation("nom", "raise", "RAISE", 1.0, 2.0),
            evaluation("nom", "call", "CALL", None, 1.0),
            evaluation("low", "raise", "RAISE", 1.0, 2.0),
            evaluation("low", "call", "CALL", None, 1.0),
            evaluation("high", "raise", "RAISE", 1.0, 2.0),
            evaluation("high", "call", "CALL", None, 1.0),
            evaluation("invented", "raise", "RAISE", 1.0, 3.0),
        ]
        with self.assertRaisesRegex(ValueError, "undeclared environment"):
            evaluate_robustness(
                decision_id="undeclared",
                environments=envs(),
                evaluations=rows,
            )


if __name__ == "__main__":
    unittest.main()

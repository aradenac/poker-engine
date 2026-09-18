#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.training.independent_profiles.evaluate_response_to_price_v1 import (  # noqa: E402
    finalize,
    predictive_gate,
    summarize_hero,
    support_audit,
)


def row(price, spr, sequence, action="CALL", sizing=None):
    out = {
        "profile": 0,
        "street": "flop",
        "relative_position": "OOP",
        "pot_type": "SRP",
        "preflop_role": "PFA",
        "sequence": sequence,
        "facing_price_to_pot": price,
        "spr": spr,
        "action": action,
        "hand_id": f"h-{price}-{spr}-{sequence}-{action}",
        "is_jam": False,
    }
    if sizing is not None:
        out["raise_sizing_ratio"] = sizing
    return out


class SupportAuditTests(unittest.TestCase):
    def test_support_is_explicit_by_price_spr_and_sequence(self):
        train = [row(0.4, 2.5, "BET") for _ in range(31)]
        train += [row(0.4, 2.5, "BET", "RAISE", 1.2) for _ in range(12)]
        validation = [row(0.4, 2.5, "BET") for _ in range(3)]
        audit = support_audit(train, validation, action_min=30, sizing_min=12)
        cells = [c for c in audit["cells"] if c["sequence"] == "BET"]
        self.assertEqual(len(cells), 1)
        cell = cells[0]
        self.assertTrue(cell["action_supported"])
        self.assertTrue(cell["sizing_supported"])
        self.assertEqual(cell["train_n"], 43)
        self.assertEqual(cell["train_raise_n"], 12)
        self.assertTrue(audit["marginals"]["price"])
        self.assertTrue(audit["marginals"]["spr"])
        self.assertTrue(audit["marginals"]["sequence"])

    def test_predictive_gate_is_predeclared_and_fail_closed(self):
        evaluation = {
            "candidate_actions": {"brier": 0.40, "ece_confidence": 0.03},
            "reference_actions": {"brier": 0.41, "ece_confidence": 0.025},
            "paired_action_log_loss": {"ci95": [-0.02, -0.001]},
        }
        sizing = {
            "candidate": {"median_absolute_log2_error": 0.95},
            "reference": {"median_absolute_log2_error": 1.00},
        }
        support = {"low_action_support_fraction": 0.05}
        gate = predictive_gate(evaluation, sizing, support)
        self.assertTrue(gate["pass"])
        evaluation["paired_action_log_loss"]["ci95"][1] = 0.001
        self.assertFalse(predictive_gate(evaluation, sizing, support)["pass"])


class HeroSensitivityTests(unittest.TestCase):
    def test_paired_hero_sensitivity_detects_action_change(self):
        def arena(actions, utilities):
            return {
                "results": [
                    {
                        "scenario_id": "s1",
                        "policy": "current",
                        "utility_bb": utilities[0],
                        "hero_actions": [{"label": actions[0], "size_ratio": 1.0}],
                    },
                    {
                        "scenario_id": "s2",
                        "policy": "current",
                        "utility_bb": utilities[1],
                        "hero_actions": [{"label": actions[1], "size_ratio": 1.5}],
                    },
                ]
            }

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            docs = {
                "reference": arena(["CALL", "RAISE"], [1.0, 2.0]),
                "candidate_nominal": arena(["CALL", "RAISE"], [1.1, 2.1]),
                "candidate_fold_low": arena(["FOLD", "RAISE"], [0.5, 2.2]),
                "candidate_fold_high": arena(["CALL", "CALL"], [1.2, 1.8]),
            }
            specs = []
            for name, doc in docs.items():
                path = root / f"{name}.json"
                path.write_text(json.dumps(doc), encoding="utf-8")
                specs.append(f"{name}={path}")
            out = root / "hero.json"
            rc = summarize_hero(SimpleNamespace(
                arena=specs,
                policy="current",
                sizing_change_threshold=0.25,
                output=str(out),
            ))
            self.assertEqual(rc, 0)
            report = json.loads(out.read_text(encoding="utf-8"))
            self.assertFalse(report["environments_weighted"])
            self.assertGreater(report["any_environment"]["first_action_changed_fraction"], 0)
            self.assertFalse(report["test_consumed"])

    def test_finalize_encodes_no_automatic_promotion_as_positive_dod_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "RESULT.partial.json").write_text(json.dumps({
                "test_consumed": False,
                "predictive_gate": {"pass": True, "checks": {"fixture": True}},
            }), encoding="utf-8")
            hero = root / "hero.json"
            hero.write_text(json.dumps({
                "test_consumed": False,
                "scenario_split": "VALIDATION",
                "environments_weighted": False,
            }), encoding="utf-8")
            rc = finalize(SimpleNamespace(run_dir=str(root), hero_sensitivity=str(hero)))
            self.assertEqual(rc, 0)
            result = json.loads((root / "RESULT.json").read_text(encoding="utf-8"))
            self.assertIs(result["automatic_promotion"], False)
            self.assertIs(result["active_model_b_changed"], False)
            self.assertIs(result["test_consumed"], False)
            self.assertIs(result["scientific_dod"]["automatic_promotion_disabled"], True)
            self.assertTrue(all(result["scientific_dod"].values()))

    def test_finalize_rejects_test_consumption(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "RESULT.partial.json").write_text(json.dumps({
                "test_consumed": False,
                "predictive_gate": {"pass": True, "checks": {}},
            }), encoding="utf-8")
            hero = root / "hero.json"
            hero.write_text(json.dumps({"test_consumed": True}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "TEST consumption"):
                finalize(SimpleNamespace(run_dir=str(root), hero_sensitivity=str(hero)))


if __name__ == "__main__":
    unittest.main()

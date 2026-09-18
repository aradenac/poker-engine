#!/usr/bin/env python3
from __future__ import annotations

import json
import unittest
from pathlib import Path

from tools.training.plan_hero_preflop_generation import (
    FALLBACK_ID,
    STATUS_BY_SUPPORT,
    TARGET_GROUPS,
    build_plan,
    generate,
)

ROOT = Path(__file__).resolve().parents[2]
AUDIT_PATH = ROOT / "analysis/hero_preflop_coverage_train.json"
PLAN_PATH = ROOT / "analysis/hero_preflop_generation_plan.json"
MD_PATH = ROOT / "analysis/hero_preflop_generation_plan.md"


class HeroPreflopGenerationPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
        cls.plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))

    def test_reproduction_is_exact(self):
        regenerated, markdown = generate(AUDIT_PATH)
        self.assertEqual(regenerated, self.plan)
        self.assertEqual(markdown, MD_PATH.read_text(encoding="utf-8"))

    def test_generation_order_is_deterministic(self):
        a = build_plan(self.audit, audit_sha256=self.plan["source"]["sha256"])
        b = build_plan(self.audit, audit_sha256=self.plan["source"]["sha256"])
        self.assertEqual(a["generation_order"], b["generation_order"])
        self.assertEqual(a["contexts"], b["contexts"])
        self.assertEqual(
            a["priority_contract"]["coverage_group_order"],
            [
                "VS_LIMPERS_ISO",
                "VS_RFI",
                "RFI_CALLERS_SQUEEZE",
                "VS_3BET",
                "VS_4BET_OR_JAM",
            ],
        )

    def test_support_tiers_map_to_explicit_readiness(self):
        self.assertEqual(
            STATUS_BY_SUPPORT,
            {
                "VERY_HIGH": "READY_FOR_GENERATION",
                "HIGH": "READY_FOR_GENERATION",
                "MEDIUM": "LOW_SUPPORT",
                "LOW": "DEFERRED",
                "SPARSE": "UNCOVERED",
            },
        )
        for row in self.plan["contexts"]:
            self.assertEqual(row["readiness"], STATUS_BY_SUPPORT[row["support_tier"]])
            self.assertEqual(
                row["exact_generation_eligible"],
                row["readiness"] == "READY_FOR_GENERATION",
            )
        self.assertEqual(
            self.plan["summary"]["status_counts"],
            {
                "DEFERRED": 80,
                "LOW_SUPPORT": 78,
                "READY_FOR_GENERATION": 44,
                "UNCOVERED": 1058,
            },
        )

    def test_stack_buckets_come_from_observed_train_quantiles(self):
        source = self.audit["effective_stack_targeted_population"]
        buckets = self.plan["stack_bucket_contract"]["buckets"]
        self.assertEqual(
            [bucket["upper_inclusive_bb"] for bucket in buckets[:-1]],
            [
                source["p10_bb"],
                source["p25_bb"],
                source["p50_bb"],
                source["p75_bb"],
                source["p90_bb"],
            ],
        )
        self.assertIsNone(buckets[0]["lower_exclusive_bb"])
        self.assertIsNone(buckets[-1]["upper_inclusive_bb"])
        for row in self.plan["contexts"]:
            median = row["effective_stack_observed"]["p50_bb"]
            bucket = next(item for item in buckets if item["id"] == row["effective_stack_bucket"])
            lower = bucket["lower_exclusive_bb"]
            upper = bucket["upper_inclusive_bb"]
            self.assertTrue(lower is None or median > lower)
            self.assertTrue(upper is None or median <= upper)

    def test_no_validation_or_test_and_no_strategy_or_ev(self):
        scope = self.plan["scope"]
        self.assertEqual(scope["split_consumed"], "TRAIN")
        for key in (
            "validation_consumed",
            "test_consumed",
            "strategy_generated",
            "ev_evaluated",
            "actions_recommended",
            "sizings_recommended",
        ):
            self.assertFalse(scope[key], key)
        self.assertEqual(
            self.plan["structural_compute_estimator"]["actual_rollouts_executed"],
            0,
        )
        for row in self.plan["contexts"]:
            for forbidden in ("action", "sizing", "ev_bb", "recommended_action", "recommended_sizing"):
                self.assertNotIn(forbidden, row)

    def test_no_context_is_invented_without_observations(self):
        audit_keys = {
            json.dumps(
                {
                    "family": row["family"],
                    "actor_position": row["actor_position"],
                    "opener_position": row["opener_position"],
                    "last_aggressor_position": row["last_aggressor_position"],
                    "callers_after_first_raise": int(row["callers_after_first_raise"]),
                    "limpers_before_first_raise": int(row["limpers_before_first_raise"]),
                    "facing_jam": bool(row["facing_jam"]),
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            for row in self.audit["matrix"]
        }
        plan_keys = {row["source_matrix_key"] for row in self.plan["contexts"]}
        self.assertEqual(plan_keys, audit_keys)
        self.assertEqual(len(self.plan["contexts"]), len(self.audit["matrix"]))
        self.assertTrue(all(row["train_observations"] > 0 for row in self.plan["contexts"]))
        self.assertTrue(all(row["distinct_hands"] > 0 for row in self.plan["contexts"]))

    def test_fallback_is_explicit_and_nearest_context_is_forbidden(self):
        fallback = self.plan["fallback_contract"]
        self.assertEqual(fallback["id"], FALLBACK_ID)
        self.assertFalse(fallback["nearest_context_allowed"])
        self.assertFalse(self.plan["exact_context_contract"]["nearest_context_allowed"])
        self.assertEqual(self.plan["exact_context_contract"]["rule"], "NO SILENT NEAREST-CONTEXT")
        self.assertTrue(fallback["forbidden"])
        for row in self.plan["contexts"]:
            self.assertEqual(row["fallback_id"], FALLBACK_ID)
            self.assertFalse(row["nearest_context_allowed"])

    def test_total_accounting_and_structural_estimator(self):
        expected = self.audit["accounting"]["targeted_population_preflop_decisions"]
        self.assertEqual(
            sum(row["train_observations"] for row in self.plan["contexts"]),
            expected,
        )
        self.assertEqual(self.plan["summary"]["train_observations_total"], expected)
        ready = [
            row for row in self.plan["contexts"]
            if row["readiness"] == "READY_FOR_GENERATION"
        ]
        self.assertEqual(len(ready), 44)
        self.assertEqual(len(self.plan["generation_order"]), 44)
        self.assertEqual(
            self.plan["structural_compute_estimator"]["ready_hand_class_cells"],
            44 * 169,
        )
        self.assertEqual(self.plan["structural_compute_estimator"]["planned_shards"], 6)
        self.assertEqual(
            sum(shard["context_count"] for shard in self.plan["shard_plan"]["shards"]),
            44,
        )

    def test_only_expected_observed_groups_are_present(self):
        self.assertEqual(
            set(self.plan["priority_contract"]["coverage_group_order"]),
            set(TARGET_GROUPS),
        )
        self.assertEqual(
            {row["coverage_group"] for row in self.plan["contexts"]},
            set(TARGET_GROUPS),
        )


if __name__ == "__main__":
    unittest.main()

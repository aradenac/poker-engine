from __future__ import annotations

import random
import unittest

from tools.simulation.paired_adaptive_preflop_ev import (
    AdaptiveBudget,
    PairedSearchError,
    common_world_seed,
    legacy_candidate_seed,
    run_fixed_historical,
    run_paired_search,
)


def world_factory(public_context, decision_id, sample_index, seed):
    rng = random.Random(seed)
    return {
        "decision_id": decision_id,
        "sample_index": sample_index,
        "public_position": public_context["position"],
        "shock": rng.gauss(0.0, 1.0),
        "tilt": rng.gauss(0.0, 0.2),
    }


def paired_ev(world, candidate_id, payload):
    return (
        payload["true_ev"]
        + world["shock"]
        + payload.get("sensitivity", 0.0) * world["tilt"]
    )


def legacy_ev(candidate_id, payload, sample_index, seed):
    rng = random.Random(seed)
    return (
        payload["true_ev"]
        + rng.gauss(0.0, 1.0)
        + payload.get("sensitivity", 0.0) * rng.gauss(0.0, 0.2)
    )


CANDIDATES = {
    "A": {"true_ev": 0.30, "sensitivity": 0.0},
    "B": {"true_ev": 0.30, "sensitivity": 0.05},
    "C": {"true_ev": -0.80, "sensitivity": 0.10},
}


class PairedAdaptivePreflopEvTests(unittest.TestCase):
    def test_two_alternatives_share_exactly_same_worlds_per_sample(self):
        seen = {}

        def evaluator(world, candidate_id, payload):
            seen.setdefault(world["sample_index"], {})[candidate_id] = dict(world)
            return paired_ev(world, candidate_id, payload)

        report = run_paired_search(
            CANDIDATES,
            decision_id="hand42:decision3",
            public_context={"position": "BTN", "board": []},
            world_factory=world_factory,
            evaluator=evaluator,
            base_seed=7,
            budget=AdaptiveBudget(4, 4, 2),
            adaptive=False,
        )
        self.assertEqual(report["search"]["worlds_materialized"], 4)
        for per_candidate in seen.values():
            self.assertEqual(per_candidate["A"], per_candidate["B"])
            self.assertEqual(per_candidate["A"], per_candidate["C"])

    def test_candidate_identity_does_not_change_common_world_seed(self):
        seeds_a = [common_world_seed("base", "decision-x", i) for i in range(5)]
        seeds_b = [common_world_seed("base", "decision-x", i) for i in range(5)]
        self.assertEqual(seeds_a, seeds_b)
        self.assertNotEqual(
            legacy_candidate_seed("base", "A", 0),
            legacy_candidate_seed("base", "B", 0),
        )

    def test_paired_delta_is_reproducible(self):
        kwargs = dict(
            candidate_payloads=CANDIDATES,
            decision_id="d",
            public_context={"position": "CO"},
            world_factory=world_factory,
            evaluator=paired_ev,
            base_seed="same",
            budget=AdaptiveBudget(8, 16, 4),
            adaptive=True,
        )
        a = run_paired_search(**kwargs)
        b = run_paired_search(**kwargs)
        self.assertEqual(a, b)
        pair = a["pairwise_deltas"]["A__minus__B"]
        self.assertGreater(pair["samples"], 0)
        self.assertIsNotNone(pair["standard_error_bb"])

    def test_max_budget_is_respected(self):
        report = run_paired_search(
            CANDIDATES,
            decision_id="budget",
            public_context={"position": "SB"},
            world_factory=world_factory,
            evaluator=paired_ev,
            base_seed=1,
            budget=AdaptiveBudget(
                initial_samples_per_alternative=4,
                max_samples_per_alternative=100,
                batch_size=10,
                max_total_rollouts=24,
            ),
            adaptive=True,
        )
        self.assertLessEqual(report["search"]["rollout_budget_used"], 24)

    def test_clearly_dominated_alternative_stops_early(self):
        report = run_paired_search(
            CANDIDATES,
            decision_id="dominated",
            public_context={"position": "BTN"},
            world_factory=world_factory,
            evaluator=paired_ev,
            base_seed=2,
            budget=AdaptiveBudget(4, 24, 4),
            adaptive=True,
        )
        self.assertEqual(report["alternatives"]["C"]["status"], "ELIMINATED")
        self.assertEqual(report["alternatives"]["C"]["samples"], 4)
        self.assertGreater(report["alternatives"]["A"]["samples"], 4)

    def test_close_alternatives_receive_more_budget(self):
        report = run_paired_search(
            CANDIDATES,
            decision_id="close",
            public_context={"position": "BTN"},
            world_factory=world_factory,
            evaluator=paired_ev,
            base_seed=3,
            budget=AdaptiveBudget(4, 24, 4),
            adaptive=True,
        )
        self.assertEqual(report["alternatives"]["C"]["samples"], 4)
        self.assertEqual(report["alternatives"]["A"]["samples"], 24)
        self.assertEqual(report["alternatives"]["B"]["samples"], 24)

    def test_fixed_historical_mode_is_reproducible(self):
        first = run_fixed_historical(
            CANDIDATES,
            evaluator=legacy_ev,
            base_seed="legacy",
            samples_per_alternative=8,
        )
        second = run_fixed_historical(
            CANDIDATES,
            evaluator=legacy_ev,
            base_seed="legacy",
            samples_per_alternative=8,
        )
        self.assertEqual(first, second)
        self.assertEqual(first["mode"], "fixed_historical")
        self.assertEqual(first["search"]["rollout_budget_used"], 24)

    def test_public_context_rejects_future_or_private_cards(self):
        for bad in (
            {"position": "BTN", "opponent_hole_cards": ["As", "Ah"]},
            {"position": "BTN", "runout": ["2c", "3d", "4h"]},
            {"position": "BTN", "future_board": ["2c"]},
        ):
            with self.subTest(bad=bad):
                with self.assertRaises(PairedSearchError):
                    run_paired_search(
                        CANDIDATES,
                        decision_id="leak",
                        public_context=bad,
                        world_factory=world_factory,
                        evaluator=paired_ev,
                        base_seed=1,
                        budget=AdaptiveBudget(2, 2, 1),
                        adaptive=False,
                    )


if __name__ == "__main__":
    unittest.main()

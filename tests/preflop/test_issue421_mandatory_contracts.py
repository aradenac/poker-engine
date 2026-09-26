#!/usr/bin/env python3
"""#421 T11 -- consolidated mandatory contract suite.

This module is the single, named regression suite the ticket asks for: every
mandatory item of the #421 generalized adverse-response cycle is one ``test_*``
method that fails closed when the contract is violated.  Nothing here needs the
network, Model B, Hero EV, a #367 run or a protected TEST row.

Mandatory items and their named tests (the mapping is machine-checked by
``test_every_mandatory_item_has_exactly_one_named_test`` and by
``tests/ci/test_issue421_contract_guards.py``):

``SAME_CONTEXT_SAME_PREDICTION``
    ``test_same_context_and_seed_produce_the_same_prediction``
``SIZING_VARIATION_DIRECT_EVALUATION``
    ``test_a_sizing_variation_is_directly_evaluated_not_looked_up``
``IN_DOMAIN_INTERPOLATION_ALLOWED``
    ``test_in_domain_interpolation_is_allowed``
``EXTRAPOLATION_OOD_FAIL_CLOSED``
    ``test_extrapolation_abstains_fail_closed``
``UNKNOWN_CATEGORY_OOD``
    ``test_unknown_category_is_out_of_domain``
``ILLEGAL_ACTIONS_NEVER_EMITTED``
    ``test_illegal_actions_are_never_emitted``
``GENERATED_SIZING_IS_LEGAL``
    ``test_generated_sizing_is_always_legal``
``NO_FUTURE_OR_PRIVATE_INFORMATION``
    ``test_no_future_or_private_information_can_change_a_decision``
``SPLIT_IS_A_FUNCTION_OF_HAND_ID``
    ``test_the_split_is_a_function_of_hand_id``
``CANDIDATE_HASH_DRIFT_FAIL_CLOSED``
    ``test_candidate_and_hash_drift_fail_closed``
``TEST_SPLIT_INACCESSIBLE``
    ``test_the_test_split_is_inaccessible``
``ACTIVE_POINTER_UNCHANGED``
    ``test_the_active_pointer_is_immutable_and_pinned``
``ISSUE367_NOT_EXECUTED``
    ``test_issue_367_is_never_executed``
"""
from __future__ import annotations

import ast
import collections
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.datasets.build_hand_history_increment import fingerprint, split_for  # noqa: E402
from tools.preflop import generalized_response_model as model  # noqa: E402
from tools.preflop import generalized_response_runtime as runtime  # noqa: E402
from tools.simulation import issue421_issue367_preflight as preflight_tool  # noqa: E402
from tools.training import build_generalized_response_dataset as dataset_builder  # noqa: E402

MANIFEST_PATH = ROOT / "analysis/issue421_generalized_response/CANDIDATE_MANIFEST.json"
MODEL_DIR = ROOT / "analysis/issue421_generalized_response/model"
PROTOCOL_PATH = ROOT / "analysis/issue421_generalized_response/FROZEN_VALIDATION_PROTOCOL.json"
DECISION_PATH = ROOT / "analysis/issue421_generalized_response/DECISION.json"
VALIDATION_RESULT_PATH = ROOT / "analysis/issue421_generalized_response/VALIDATION_RESULT.json"
DATASET_PATH = ROOT / "analysis/issue421_generalized_response/dataset/GENERALIZED_RESPONSE_DATASET.jsonl"
DATASET_MANIFEST_PATH = (
    ROOT / "analysis/issue421_generalized_response/dataset/GENERALIZED_RESPONSE_DATASET.json"
)

#: The frozen interpolation declaration every direct price/sizing query must carry.
INTERPOLATION = "linear_spline_partition_of_unity"

#: Every mandatory ticket item, its stable id and the named test that pins it.
MANDATORY_CONTRACT_ITEMS: tuple[dict[str, str], ...] = (
    {
        "id": "SAME_CONTEXT_SAME_PREDICTION",
        "test": "test_same_context_and_seed_produce_the_same_prediction",
        "description": "the same public context and the same frozen seed/config are byte-identical",
    },
    {
        "id": "SIZING_VARIATION_DIRECT_EVALUATION",
        "test": "test_a_sizing_variation_is_directly_evaluated_not_looked_up",
        "description": "a sizing/price variation is recomputed directly, never a nearest-cell lookup",
    },
    {
        "id": "IN_DOMAIN_INTERPOLATION_ALLOWED",
        "test": "test_in_domain_interpolation_is_allowed",
        "description": "an unobserved but in-domain price is answered by interpolation, not abstained",
    },
    {
        "id": "EXTRAPOLATION_OOD_FAIL_CLOSED",
        "test": "test_extrapolation_abstains_fail_closed",
        "description": "any stack/price/sizing extrapolation abstains fail-closed",
    },
    {
        "id": "UNKNOWN_CATEGORY_OOD",
        "test": "test_unknown_category_is_out_of_domain",
        "description": "a category never observed in TRAIN is out-of-domain",
    },
    {
        "id": "ILLEGAL_ACTIONS_NEVER_EMITTED",
        "test": "test_illegal_actions_are_never_emitted",
        "description": "illegal actions carry no probability mass and are never selected",
    },
    {
        "id": "GENERATED_SIZING_IS_LEGAL",
        "test": "test_generated_sizing_is_always_legal",
        "description": "every generated RAISE/JAM target is inside the legal window",
    },
    {
        "id": "NO_FUTURE_OR_PRIVATE_INFORMATION",
        "test": "test_no_future_or_private_information_can_change_a_decision",
        "description": "future/private fields are neither consumed nor able to move a decision",
    },
    {
        "id": "SPLIT_IS_A_FUNCTION_OF_HAND_ID",
        "test": "test_the_split_is_a_function_of_hand_id",
        "description": "the fold assignment is a deterministic function of hand_id, one fold per hand",
    },
    {
        "id": "CANDIDATE_HASH_DRIFT_FAIL_CLOSED",
        "test": "test_candidate_and_hash_drift_fail_closed",
        "description": "a candidate/hash drift fails closed before any prediction is produced",
    },
    {
        "id": "TEST_SPLIT_INACCESSIBLE",
        "test": "test_the_test_split_is_inaccessible",
        "description": "the TEST split is refused by every loader and never appears in the dataset",
    },
    {
        "id": "ACTIVE_POINTER_UNCHANGED",
        "test": "test_the_active_pointer_is_immutable_and_pinned",
        "description": "the active Model A/B pointers and registries stay byte-identical to their pins",
    },
    {
        "id": "ISSUE367_NOT_EXECUTED",
        "test": "test_issue_367_is_never_executed",
        "description": "no #367 run, Hero EV, rollout or recommendation is computed by this cycle",
    },
)


def base_context(**overrides: object) -> dict:
    """A public, in-domain UNOPENED context immediately before LJ acts."""
    context: dict = {
        "family": "UNOPENED",
        "actor_position": "LJ",
        "aggressor_position": None,
        "caller_count": 0,
        "limper_count": 0,
        "raise_level": 0,
        "live_positions": ["LJ", "HJ", "CO", "BTN", "SB", "BB"],
        "table_size": 6,
        "to_call_bb": 1.0,
        "pot_before_bb": 1.5,
        "effective_stack_bb": 70.975,
        "split": "TRAIN",
    }
    context.update(overrides)
    return context


class Issue421MandatoryContractTests(unittest.TestCase):
    """One named, fail-closed test per mandatory #421 contract item."""

    _preflight: dict | None = None

    @classmethod
    def setUpClass(cls) -> None:
        if not MANIFEST_PATH.is_file() or not DATASET_PATH.is_file():
            raise unittest.SkipTest("the frozen #421 candidate/dataset is absent from this worktree")
        cls.manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        cls.candidate_entry = cls.manifest["candidate"]
        cls.candidate_id = str(cls.candidate_entry["candidate_id"])
        cls.candidate_sha256 = str(cls.candidate_entry["canonical_payload_sha256"])
        cls.protocol = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))
        cls.decision = json.loads(DECISION_PATH.read_text(encoding="utf-8"))
        cls.validation = json.loads(VALIDATION_RESULT_PATH.read_text(encoding="utf-8"))
        cls.dataset_manifest = json.loads(DATASET_MANIFEST_PATH.read_text(encoding="utf-8"))
        cls.dataset_summary = cls._summarise_dataset()
        runtime.clear_runtime_caches()
        cls.runtime = runtime.GeneralizedResponseRuntime(candidate_id=cls.candidate_id)

    @classmethod
    def preflight_document(cls) -> dict:
        if cls._preflight is None:
            cls._preflight, _ = preflight_tool.build()
        return cls._preflight

    @classmethod
    def _summarise_dataset(cls) -> dict:
        """One streaming pass: public keys, per-hand fold and per-fold fingerprints."""
        keys: set[str] = set()
        missing: set[str] = set(dataset_builder.ROW_FIELDS)
        for field in dataset_builder.ROW_FIELDS:
            missing.discard(field)
        hand_split: dict[str, str] = {}
        split_hands: dict[str, set[str]] = collections.defaultdict(set)
        split_rows: collections.Counter[str] = collections.Counter()
        hands_in_two_splits = 0
        test_rows = 0
        rows = 0
        with DATASET_PATH.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                rows += 1
                keys.update(row)
                missing -= set(row)
                split = str(row["split"])
                hand_id = str(row["hand_id"])
                split_rows[split] += 1
                split_hands[split].add(hand_id)
                if split == "TEST":
                    test_rows += 1
                previous = hand_split.setdefault(hand_id, split)
                if previous != split:
                    hands_in_two_splits += 1
        return {
            "rows": rows,
            "keys": keys,
            "missing_keys": missing,
            "extra_keys": sorted(keys - set(dataset_builder.ROW_FIELDS)),
            "hand_split": hand_split,
            "split_hands": dict(split_hands),
            "split_rows": dict(split_rows),
            "hands_in_two_splits": hands_in_two_splits,
            "test_rows": test_rows,
        }

    # ------------------------------------------------------------- item tests
    def test_same_context_and_seed_produce_the_same_prediction(self) -> None:
        contexts = (
            base_context(),
            base_context(target_total_bb=3.0),
            base_context(to_call_bb=2.0, pot_before_bb=4.0, effective_stack_bb=60.0),
            base_context(
                family="VS_LIMPERS",
                actor_position="BB",
                limper_count=1,
                live_positions=["BTN", "SB", "BB"],
                to_call_bb=0.5,
                pot_before_bb=2.5,
            ),
        )
        for context in contexts:
            for action in (None, "RAISE", "JAM"):
                first = self.runtime.resolve(context, action=action)
                second = self.runtime.resolve(context, action=action)
                with self.subTest(action=action, path=context["actor_position"]):
                    self.assertEqual(first, second)
                    self.assertEqual(
                        first["decision_canonical_sha256"],
                        second["decision_canonical_sha256"],
                    )
                    self.assertEqual(
                        first["decision_canonical_sha256"],
                        runtime.decision_canonical_sha256(first),
                    )
                    self.assertEqual(first["deterministic_seed"], int(self.runtime.candidate["seed"]))
        # A fresh handle over the same frozen candidate carries the same identity.
        fresh = runtime.GeneralizedResponseRuntime(candidate_id=self.candidate_id)
        self.assertEqual(
            fresh.resolve(base_context(target_total_bb=3.0), action="RAISE")[
                "decision_canonical_sha256"
            ],
            self.runtime.resolve(base_context(target_total_bb=3.0), action="RAISE")[
                "decision_canonical_sha256"
            ],
        )
        with self.assertRaises(runtime.GeneralizedResponseRuntimeError) as caught:
            self.runtime.resolve(base_context(), seed=int(self.runtime.candidate["seed"]) + 1)
        self.assertEqual(caught.exception.code, runtime.FAIL_CLOSED_SEED_MISMATCH)

    def _usable(self, **overrides: object) -> dict:
        document = self.runtime.resolve(base_context(**overrides), action="RAISE")
        self.assertTrue(document["usable"], document["status"])
        return document

    def test_a_sizing_variation_is_directly_evaluated_not_looked_up(self) -> None:
        low = self._usable(target_total_bb=2.5)["action_probabilities"]["RAISE"]
        middle = self._usable(target_total_bb=2.75)["action_probabilities"]["RAISE"]
        high = self._usable(target_total_bb=3.0)["action_probabilities"]["RAISE"]
        # A nearest-cell lookup would return one of the queried values exactly.
        self.assertNotEqual(low, middle)
        self.assertNotEqual(middle, high)
        self.assertTrue(high < middle < low, (low, middle, high))
        # The channel is continuous: an arbitrarily small move still moves it.
        epsilon = self._usable(target_total_bb=3.0001)["action_probabilities"]["RAISE"]
        self.assertLess(epsilon, high)
        self.assertLess(abs(epsilon - high), abs(high - middle))
        document = self._usable(target_total_bb=3.0)
        self.assertEqual(document["request"]["evaluation"], "direct_recomputation")
        self.assertEqual(document["request"]["interpolation"], INTERPOLATION)
        self.assertEqual(document["prediction"]["sizing"]["source"], "context")
        self.assertEqual(document["prediction"]["sizing"]["interpolation"], INTERPOLATION)
        flags = document["provenance"]["identity_flags"]
        self.assertFalse(flags["nearest_price_substituted"])
        self.assertFalse(flags["nearest_context_substituted"])
        self.assertFalse(document["sizing"]["nearest_price_substituted"])
        self.assertFalse(document["sizing"]["nearest_context_substituted"])

    def test_in_domain_interpolation_is_allowed(self) -> None:
        knots = [float(knot) for knot in self.runtime.candidate["config"]["sizing_axis_knots"]]
        document = self._usable(target_total_bb=2.75)
        ratio = float(document["request"]["sizing_ratio"])
        # 2.75bb / 2.5bb == 1.1 lands strictly between the 0.8 and 1.2 knots:
        # the query is in-domain but was never an observed grid point.
        self.assertTrue(
            any(lower < ratio < upper for lower, upper in zip(knots, knots[1:])),
            f"sizing ratio {ratio} is not an interior knot value of {knots}",
        )
        self.assertNotEqual(document["status"], runtime.STATUS_ABSTAIN)
        self.assertTrue(document["usable"])
        self.assertEqual(document["ood"]["hard_reasons"], [])
        self.assertFalse(document["ood"]["signals"]["axes"]["sizing_ratio"]["extrapolation"])
        self.assertEqual(document["request"]["interpolation"], INTERPOLATION)
        self.assertEqual(document["prediction"]["sizing"]["interpolation"], INTERPOLATION)

    def test_extrapolation_abstains_fail_closed(self) -> None:
        probes = (
            (base_context(effective_stack_bb=5000.0), "EXTRAPOLATION_STACK"),
            (base_context(target_total_bb=5000.0), "EXTRAPOLATION_SIZING"),
            (
                base_context(to_call_bb=4000.0, pot_before_bb=100.0, effective_stack_bb=4000.0),
                "EXTRAPOLATION_PRICE",
            ),
        )
        for context, reason in probes:
            document = self.runtime.resolve(context, action="RAISE")
            with self.subTest(reason=reason):
                self.assertEqual(document["status"], runtime.STATUS_ABSTAIN)
                self.assertFalse(document["usable"])
                self.assertTrue(document["abstain"])
                self.assertTrue(document["fail_closed"])
                self.assertEqual(document["fail_closed_reason"], runtime.OOD_ABSTAIN_REASON)
                self.assertIn(reason, document["ood"]["hard_reasons"])
                self.assertIsNone(document["selected_action"])
                self.assertIsNone(document["selected_sizing_bb"])
                self.assertIsNone(document["sizing"])
                self.assertFalse(document["consumer"]["usable"])

    def test_unknown_category_is_out_of_domain(self) -> None:
        probes = ({"family": "NOT_A_FAMILY"}, {"actor_position": "NOT_A_POSITION"})
        for overrides in probes:
            document = self.runtime.resolve(base_context(**overrides), action="RAISE")
            with self.subTest(**overrides):
                self.assertEqual(document["status"], runtime.STATUS_ABSTAIN)
                self.assertIn("UNSEEN_CATEGORY", document["ood"]["hard_reasons"])
                self.assertIsNone(document["selected_action"])
                self.assertIsNone(document["sizing"])

    def test_illegal_actions_are_never_emitted(self) -> None:
        contexts = (
            base_context(),
            base_context(to_call_bb=0.0),
            base_context(facing_all_in=True),
            base_context(legal_actions=["FOLD", "CALL"]),
            base_context(
                family="VS_LIMPERS",
                actor_position="BB",
                limper_count=1,
                live_positions=["BTN", "SB", "BB"],
                to_call_bb=0.5,
                pot_before_bb=2.5,
            ),
        )
        for context in contexts:
            document = self.runtime.resolve(context)
            legal = set(document["legal_actions"])
            with self.subTest(legal=sorted(legal)):
                self.assertEqual(document["illegal_mass"], 0.0)
                self.assertAlmostEqual(document["probability_sum"], 1.0, places=9)
                for action in model.ACTIONS:
                    if action not in legal:
                        self.assertEqual(document["action_probabilities"][action], 0.0, action)
                if document["selected_action"] is not None:
                    self.assertIn(document["selected_action"], legal)
        for context, action in (
            (base_context(), "CHECK"),
            (base_context(facing_all_in=True), "JAM"),
            (base_context(legal_actions=["FOLD", "CALL"]), "RAISE"),
        ):
            with self.subTest(action=action):
                with self.assertRaises(runtime.GeneralizedResponseRuntimeError) as caught:
                    self.runtime.resolve(context, action=action)
                self.assertEqual(caught.exception.code, runtime.FAIL_CLOSED_ILLEGAL_ACTION)

    def test_generated_sizing_is_always_legal(self) -> None:
        resolved = 0
        probes = (
            {"target_total_bb": 2.5},
            {"target_total_bb": 3.0},
            {
                "raise_level": 1,
                "actor_contribution_bb": 5.0,
                "to_call_bb": 10.0,
                "pot_before_bb": 25.0,
                "effective_stack_bb": 100.0,
            },
        )
        for overrides in probes:
            for action in ("RAISE", "JAM"):
                document = self.runtime.resolve(base_context(**overrides), action=action)
                sizing = document["sizing"]
                if not document["usable"] or sizing is None:
                    continue
                window = sizing["legal_window"]
                with self.subTest(action=action, status=sizing["status"], **overrides):
                    self.assertFalse(sizing["nearest_price_substituted"])
                    self.assertFalse(sizing["nearest_context_substituted"])
                    if sizing["status"] != "RESOLVED":
                        self.assertEqual(sizing["generated_sizings_bb"], [])
                        self.assertIsNone(document["selected_sizing_bb"])
                        continue
                    resolved += 1
                    self.assertEqual(sizing["illegal_count"], 0)
                    self.assertTrue(sizing["generated_sizings_bb"])
                    for target in sizing["generated_sizings_bb"]:
                        self.assertGreaterEqual(float(target), float(window["floor_bb"]) - 1e-9)
                        self.assertLessEqual(float(target), float(window["cap_bb"]) + 1e-9)
                    self.assertGreaterEqual(
                        float(document["selected_sizing_bb"]), float(window["floor_bb"]) - 1e-9
                    )
                    self.assertLessEqual(
                        float(document["selected_sizing_bb"]), float(window["cap_bb"]) + 1e-9
                    )
        self.assertGreater(resolved, 0)
        # The defensive invariant itself fails closed on a smuggled illegal target.
        legal_sizing = {
            "status": "RESOLVED",
            "nearest_price_substituted": False,
            "nearest_context_substituted": False,
            "illegal_count": 0,
            "generated_sizings_bb": [1.5],
            "legal_window": {"floor_bb": 1.0, "cap_bb": 2.0},
        }
        for mutation in (
            {"illegal_count": 1},
            {"generated_sizings_bb": [5.0]},
            {"nearest_price_substituted": True},
            {"nearest_context_substituted": True},
        ):
            with self.subTest(mutation=mutation):
                with self.assertRaises(runtime.GeneralizedResponseRuntimeError) as caught:
                    runtime._verify_generated_sizings({**legal_sizing, **mutation})
                self.assertEqual(caught.exception.code, runtime.FAIL_CLOSED_ILLEGAL_SIZING)

    def test_no_future_or_private_information_can_change_a_decision(self) -> None:
        clean = self.runtime.resolve(base_context(target_total_bb=3.0), action="RAISE")
        leaked = self.runtime.resolve(
            base_context(
                target_total_bb=3.0,
                future_actions=[{"action": "RAISE", "position": "HJ"}],
                hole_cards=["As", "Kd"],
                known_cards=["As"],
                board=["2c", "3d", "4h"],
                showdown_winner="LJ",
                is_hero=True,
            ),
            action="RAISE",
        )
        self.assertEqual(clean["decision_canonical_sha256"], leaked["decision_canonical_sha256"])
        self.assertEqual(clean["action_probabilities"], leaked["action_probabilities"])
        self.assertEqual(clean["selected_action"], leaked["selected_action"])

        scope = self.dataset_manifest["scope"]
        self.assertTrue(scope["public_only"])
        self.assertFalse(scope["future_information_consumed"])
        self.assertFalse(scope["hole_cards_consumed"])
        self.assertEqual(scope["state_timing"], "BEFORE_ACTION")
        self.assertEqual(scope["player_role"], "ADVERSE_NON_HERO")
        self.assertEqual(scope["excluded_actions"], ["CHECK"])
        # No persisted row carries a private/future field or an undeclared key.
        self.assertEqual(self.dataset_summary["extra_keys"], [])
        self.assertEqual(sorted(self.dataset_summary["missing_keys"]), [])
        self.assertFalse(self.dataset_summary["keys"] & set(dataset_builder.FORBIDDEN_ROW_KEYS))
        # The builder's public-row guard itself fails closed on a leak.
        public_row = {
            "hand_id": "261672888042",
            "split": "TRAIN",
            "table_size": 6,
            "family": "UNOPENED",
            "actor_position": "LJ",
            "aggressor_position": None,
            "limper_count": 0,
            "caller_count": 0,
            "live_positions": ["LJ", "HJ", "CO", "BTN", "SB", "BB"],
            "raise_level": 0,
            "to_call_bb": 1.0,
            "pot_before_bb": 1.5,
            "pot_odds": 0.4,
            "price_to_pot": 0.666667,
            "effective_stack_bb": 70.975,
            "target_total_bb": None,
            "observed_sizing_bb": None,
            "action": "FOLD",
        }
        dataset_builder.assert_public_row(public_row)
        for leak in ("known_cards", "hole_cards", "future_actions", "history", "board", "is_hero"):
            with self.subTest(leak=leak):
                with self.assertRaises(ValueError):
                    dataset_builder.assert_public_row({**public_row, leak: ["As"]})
        with self.assertRaises(ValueError):
            dataset_builder.assert_public_row({**public_row, "undeclared_field": 1})
        with self.assertRaises(ValueError):
            dataset_builder.assert_public_row(
                {key: value for key, value in public_row.items() if key != "action"}
            )
        # A Hero row is dropped, never projected into the adverse dataset.
        self.assertIsNone(
            dataset_builder.project_response_row(
                {
                    "hand_id": "261672888042",
                    "split": "TRAIN",
                    "street": "PREFLOP",
                    "is_hero": True,
                    "action": "RAISE",
                    "preflop_context_v1": {"to_call_bb": 1.0, "pot_before_bb": 1.5},
                },
                split="TRAIN",
            )
        )
        for forbidden in ("HIDDEN_HAND_IMPUTATION", "PSEUDO_OBSERVATION"):
            self.assertIn(forbidden, self.protocol["forbidden"])

    def test_the_split_is_a_function_of_hand_id(self) -> None:
        for hand_id in ("261672888042", "hand-1", "hand-2", "0", "ffff"):
            self.assertEqual(split_for(hand_id), split_for(hand_id))
            self.assertIn(split_for(hand_id), {"TRAIN", "VALIDATION", "TEST"})
        summary = self.dataset_summary
        for hand_id, split in summary["hand_split"].items():
            with self.subTest(hand_id=hand_id):
                self.assertEqual(split_for(hand_id), split)
        self.assertEqual(summary["hands_in_two_splits"], 0)
        self.assertEqual(set(summary["split_rows"]), set(model.TRAIN_SPLITS))
        self.assertNotIn("TEST", summary["split_rows"])
        self.assertFalse(
            summary["split_hands"].get("TRAIN", set())
            & summary["split_hands"].get("VALIDATION", set())
        )
        for split in model.TRAIN_SPLITS:
            with self.subTest(split=split):
                hands = summary["split_hands"].get(split, set())
                manifest_split = self.dataset_manifest["splits"][split]
                self.assertEqual(manifest_split["hands"], len(hands))
                self.assertEqual(manifest_split["response_rows"], summary["split_rows"][split])
                self.assertEqual(manifest_split["hand_ids_fingerprint_sha256"], fingerprint(hands))
        self.assertEqual(summary["rows"], self.dataset_manifest["accounting"]["total"]["response_rows"])
        # The evaluation contract pairs decisions by hand_id too.
        self.assertEqual(self.protocol["metrics"]["paired_unit"], "hand_id")
        self.assertEqual(
            self.protocol["metrics"]["pairing_rule"],
            self.protocol["non_inferiority_rule"]["pairing_rule"],
        )
        self.assertEqual(self.protocol["non_inferiority_rule"]["paired_unit"], "hand_id")

    def test_candidate_and_hash_drift_fail_closed(self) -> None:
        with self.assertRaises(runtime.GeneralizedResponseRuntimeError) as caught:
            runtime.GeneralizedResponseRuntime(
                candidate_id=self.candidate_id, expected_candidate_sha256="0" * 64
            )
        self.assertEqual(caught.exception.code, runtime.FAIL_CLOSED_CANDIDATE_HASH_MISMATCH)
        self.assertIn(self.candidate_sha256, caught.exception.message)
        with self.assertRaises(runtime.GeneralizedResponseRuntimeError) as caught:
            runtime.GeneralizedResponseRuntime(
                candidate_id=self.candidate_id, expected_candidate_sha256="abc"
            )
        self.assertEqual(caught.exception.code, runtime.FAIL_CLOSED_CANDIDATE_HASH_MISMATCH)
        with self.assertRaises(runtime.GeneralizedResponseRuntimeError) as caught:
            runtime.GeneralizedResponseRuntime("not-a-candidate")
        self.assertEqual(caught.exception.code, runtime.FAIL_CLOSED_CANDIDATE_NOT_FOUND)
        # A drifted artifact on disk, and a stale declared digest, both fail closed
        # before a single prediction is produced.
        original = json.loads(
            (MODEL_DIR / Path(self.runtime.entry["path"]).name).read_text(encoding="utf-8")
        )
        tampered = json.loads(json.dumps(original))
        tampered["params"]["prior"]["FOLD"] = 0.9
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "candidate_tampered.json"
            target.write_text(json.dumps(tampered, sort_keys=True, indent=2) + "\n", encoding="utf-8")
            with self.assertRaises(runtime.GeneralizedResponseRuntimeError) as caught:
                runtime.GeneralizedResponseRuntime(target)
            self.assertIn(
                caught.exception.code,
                {runtime.FAIL_CLOSED_CANDIDATE_HASH_MISMATCH, runtime.FAIL_CLOSED_CANDIDATE_INVALID},
            )
        stale = json.loads(json.dumps(original))
        stale["params"]["prior"]["JAM"] = 0.25
        with self.assertRaises(runtime.GeneralizedResponseRuntimeError) as caught:
            runtime.GeneralizedResponseRuntime(stale)
        self.assertIn(
            caught.exception.code,
            {runtime.FAIL_CLOSED_CANDIDATE_HASH_MISMATCH, runtime.FAIL_CLOSED_CANDIDATE_INVALID},
        )
        self.assertTrue(
            self.runtime.metadata()["guarantees"]["fail_closed_on_candidate_hash_mismatch"]
        )
        self.assertIn(runtime.FAIL_CLOSED_CANDIDATE_HASH_MISMATCH, runtime.FAIL_CLOSED_CODES)
        # The frozen protocol is content-addressed too: a drifted sidecar is
        # refused before the #367 admission rule can be re-read.
        sidecar = preflight_tool.PROTOCOL_SIDECAR.read_text(encoding="utf-8").split()
        self.assertEqual(
            sidecar[0], hashlib.sha256(PROTOCOL_PATH.read_bytes()).hexdigest()
        )
        self.assertEqual(preflight_tool.load_frozen_protocol()["byte_sha256"], sidecar[0])
        with tempfile.TemporaryDirectory() as folder:
            drifted = Path(folder) / "FROZEN_VALIDATION_PROTOCOL.sha256"
            drifted.write_text(
                "0" * 64 + "  FROZEN_VALIDATION_PROTOCOL.json\n", encoding="utf-8"
            )
            with mock.patch.object(preflight_tool, "PROTOCOL_SIDECAR", drifted):
                with self.assertRaises(preflight_tool.PreflightError):
                    preflight_tool.load_frozen_protocol()
        frozen = preflight_tool.load_frozen_protocol()
        with mock.patch.object(preflight_tool, "CANDIDATE_CANONICAL_SHA256", "0" * 64):
            with self.assertRaises(preflight_tool.PreflightError):
                preflight_tool.load_candidate_manifest(frozen)

    def test_the_test_split_is_inaccessible(self) -> None:
        with self.assertRaises(runtime.GeneralizedResponseRuntimeError) as caught:
            self.runtime.resolve(base_context(split="TEST"))
        self.assertEqual(caught.exception.code, runtime.FAIL_CLOSED_TEST_SPLIT)
        with self.assertRaises(Exception):
            model.read_dataset_rows(DATASET_PATH, splits=["TEST"])
        with self.assertRaises(Exception):
            dataset_builder.require_consumable_splits(("TEST",))
        with self.assertRaises(dataset_builder.TestSplitForbidden):
            dataset_builder.iter_response_rows([], "TEST")
        self.assertEqual(self.dataset_manifest["scope"]["refused_splits"], ["TEST"])
        self.assertEqual(self.dataset_summary["test_rows"], 0)
        self.assertNotIn("TEST", self.dataset_summary["split_rows"])
        self.assertFalse(self.protocol["evaluation"]["test_consumed"])
        self.assertFalse(self.protocol["issue367_rule"]["test_consumed"])
        self.assertFalse(self.protocol["holdout_boundary"]["test_consumed"])
        self.assertFalse(self.validation["test_consumed"])
        self.assertFalse(self.decision["test_consumed"])
        self.assertFalse(self.validation["test_authorized"])
        self.assertFalse(self.decision["test_authorized"])
        self.assertIs(runtime.TEST_CONSUMED, False)

    def test_the_active_pointer_is_immutable_and_pinned(self) -> None:
        before = preflight_tool.protected_hashes()
        pinned = {
            self.protocol["active_references"]["active_model_a_preflop"]["path"]: self.protocol[
                "active_references"
            ]["active_model_a_preflop"]["sha256"],
            self.protocol["active_references"]["active_model_b_postflop"]["path"]: self.protocol[
                "active_references"
            ]["active_model_b_postflop"]["sha256"],
            self.protocol["active_references"]["training_registry"]["path"]: self.protocol[
                "active_references"
            ]["training_registry"]["sha256"],
            self.protocol["active_references"]["populations_registry"]["path"]: self.protocol[
                "active_references"
            ]["populations_registry"]["sha256"],
        }
        for path, digest in pinned.items():
            with self.subTest(path=path):
                self.assertIn(path, before)
                self.assertEqual(before[path], digest)
        # Exercise the model, the sizing channel and the preflight, then re-check.
        for context in (
            base_context(),
            base_context(target_total_bb=3.0),
            base_context(effective_stack_bb=5000.0),
            base_context(actor_position="NOT_A_POSITION"),
        ):
            self.runtime.resolve(context, action="RAISE")
        self.preflight_document()
        self.assertEqual(before, preflight_tool.protected_hashes())
        self.assertFalse(self.runtime.audit()["active_model_pointer_mutated"])
        self.assertFalse(self.decision["active_pointer_mutated"])
        self.assertFalse(self.decision["active_model_pointer_mutation"])
        self.assertFalse(self.validation["active_pointer_mutated"])
        self.assertFalse(self.validation["active_pointer_mutation"])
        self.assertFalse(self.protocol["publication"]["active_model_pointer_mutation"])
        self.assertFalse(self.protocol["issue367_rule"]["active_model_pointer_mutation"])
        self.assertFalse(
            self.runtime.resolve(base_context(), action="RAISE")["provenance"]["identity_flags"][
                "active_model_pointer_mutated"
            ]
        )
        self.assertIs(runtime.ACTIVE_POINTER_MUTATED, False)

    def test_issue_367_is_never_executed(self) -> None:
        document = self.preflight_document()
        boundary = document["boundary"]
        self.assertFalse(boundary["issue367_executed"])
        self.assertFalse(boundary["hero_ev_executed"])
        self.assertFalse(boundary["recommendation_computed"])
        self.assertFalse(boundary["hero_ev_runner_imported"])
        self.assertEqual(boundary["rollouts_executed"], 0)
        self.assertEqual(boundary["ev_values_computed"], 0)
        scan = document["self_scans"]["hero_ev_scan"]
        self.assertEqual(scan["result"], "PASS")
        self.assertEqual(scan["hits"], [])
        self.assertEqual(scan["forbidden_modules_imported_during_build"], [])
        self.assertFalse(scan["runner_module_imported_by_preflight"])
        self.assertEqual(preflight_tool.verify_no_hero_ev_execution()["result"], "PASS")
        self.assertEqual(preflight_tool.verify_no_holdout_access()["result"], "PASS")
        # This consolidated suite itself never imports the #367 / Hero EV runner
        # families (a static, process-order-independent proof).
        self.assertEqual(self._hero_ev_references_in_this_module(), [])
        self.assertFalse(self.decision["issue367_authorized"])
        self.assertFalse(self.protocol["issue367_rule"]["authorized_at_freeze"])
        self.assertFalse(self.protocol["issue367_rule"]["hero_ev_consumed"])
        self.assertFalse(self.protocol["issue367_rule"]["model_b_consumed"])
        self.assertFalse(self.protocol["issue367_rule"]["promotion_performed"])
        self.assertFalse(
            self.runtime.resolve(base_context(), action="RAISE")["provenance"]["issue367"]["authorized"]
        )

    @staticmethod
    def _hero_ev_references_in_this_module() -> list[str]:
        """Forbidden Hero EV / rollout references in this suite's own source."""
        tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
        used: set[str] = set()
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                used.add(node.id)
            elif isinstance(node, ast.Attribute):
                used.add(node.attr)
            elif isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.append(node.module or "")
                imported.extend(alias.name for alias in node.names)
        hits = sorted(used & set(preflight_tool.HERO_EV_FORBIDDEN_SYMBOLS))
        markers = tuple(preflight_tool.HERO_EV_FORBIDDEN_IMPORT_MARKERS)
        # The preflight module is this ticket's own evidence surface, not a runner.
        own = "tools.simulation.issue421_issue367_preflight"
        own_names = {own, own.rsplit(".", 1)[-1]}
        hits.extend(
            name
            for name in imported
            if name not in own_names and any(marker in name.lower() for marker in markers)
        )
        return sorted(set(hits))

    # -------------------------------------------------------- suite integrity
    def test_every_mandatory_item_has_exactly_one_named_test(self) -> None:
        ids = [item["id"] for item in MANDATORY_CONTRACT_ITEMS]
        mapped = [item["test"] for item in MANDATORY_CONTRACT_ITEMS]
        self.assertEqual(len(ids), len(set(ids)), "duplicate mandatory item id")
        self.assertEqual(len(mapped), len(set(mapped)), "two items map to one test")
        for item in MANDATORY_CONTRACT_ITEMS:
            with self.subTest(item=item["id"]):
                self.assertTrue(item["description"])
                method = getattr(self.__class__, item["test"], None)
                self.assertTrue(callable(method), f"{item['test']} is missing")
        declared = {name for name in dir(self.__class__) if name.startswith("test_")}
        self.assertEqual(
            declared - set(mapped),
            {"test_every_mandatory_item_has_exactly_one_named_test"},
            "a named test in this suite is not declared as a mandatory item",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)

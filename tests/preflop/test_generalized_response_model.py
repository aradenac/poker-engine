#!/usr/bin/env python3
"""#421 guard: generalizing adverse-response model library (two architectures, stdlib).

Covers every acceptance criterion of the task:

* at least two architectures are trainable and comparable on the same dataset;
* identical context + seed/config => identical prediction (and the fit does not
  depend on the input row order);
* the returned distribution is legal, sums to exactly 1.0, and illegal actions
  are masked *before* the final normalization;
* a variation of ``target_total_bb`` is recomputed directly and continuously by
  the price/sizing spline, never by substituting a neighbouring cell;
* the module and its documents depend on the standard library only;
* candidates persist byte-reproducibly with a canonical payload hash that
  matches ``contracts/training/generalized-response-model.schema.json``.

``jsonschema`` is not a declared dependency of this repository, so the contract
is validated with an explicit, reviewable keyword subset, mirroring the
convention of ``tests/training/test_build_generalized_response_dataset.py``.
The full-dataset fit is opt-in via ``POKER_GENERALIZED_RESPONSE_FULL_FIT=1``;
the fast path fits a deterministic stride sample of the persisted TRAIN rows.
"""
from __future__ import annotations

import ast
import contextlib
import io
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.preflop import generalized_response_model as model  # noqa: E402

MODULE_PATH = ROOT / "tools/preflop/generalized_response_model.py"
CONTRACT_PATH = ROOT / "contracts/training/generalized-response-model.schema.json"
MODEL_DIR = ROOT / "analysis/issue421_generalized_response/model"

FULL_FIT = os.environ.get("POKER_GENERALIZED_RESPONSE_FULL_FIT") == "1"

#: Deterministic stride used to keep the real-dataset tests fast while still
#: exercising the persisted TRAIN/VALIDATION rows end to end.
TRAIN_STRIDE = 4
VALIDATION_STRIDE = 8

FAST_CONFIG = model.make_config(tuning_max_rows=1500, holdout_modulus=5)


# ---------------------------------------------------------------------------
# minimal, reviewable JSON-Schema subset validator
# ---------------------------------------------------------------------------


def _resolve(schema: dict, root: dict) -> dict:
    while isinstance(schema, dict) and "$ref" in schema:
        node: object = root
        for part in str(schema["$ref"]).lstrip("#/").split("/"):
            node = node[part]  # type: ignore[index]
        schema = node  # type: ignore[assignment]
    return schema


def _errors(value: object, schema: dict, root: dict, path: str) -> list[str]:
    schema = _resolve(schema, root)
    if not isinstance(schema, dict):
        return [f"{path}: schema node is not an object"]
    errors: list[str] = []
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: expected const {schema['const']!r}, got {value!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {value!r} is outside {schema['enum']!r}")
    if "oneOf" in schema:
        matches = sum(1 for branch in schema["oneOf"] if not _errors(value, branch, root, path))
        if matches != 1:
            errors.append(f"{path}: expected exactly one oneOf branch, got {matches}")
    if "anyOf" in schema:
        if not any(not _errors(value, branch, root, path) for branch in schema["anyOf"]):
            errors.append(f"{path}: no anyOf branch matched")
    for branch in schema.get("allOf") or []:
        errors.extend(_errors(value, branch, root, path))
    if "not" in schema and not _errors(value, schema["not"], root, path):
        errors.append(f"{path}: matched a forbidden 'not' schema")
    expected_types = schema.get("type")
    if expected_types is not None:
        candidates = expected_types if isinstance(expected_types, list) else [expected_types]
        if not any(_is_type(value, candidate) for candidate in candidates):
            errors.append(f"{path}: expected type {expected_types!r}, got {type(value).__name__}")
            return errors
    if isinstance(value, dict):
        for key in schema.get("required") or []:
            if key not in value:
                errors.append(f"{path}: missing required property {key!r}")
        properties = schema.get("properties") or {}
        for key, child in value.items():
            if key in properties:
                errors.extend(_errors(child, properties[key], root, f"{path}.{key}"))
                continue
            extra = schema.get("additionalProperties", True)
            if extra is False:
                errors.append(f"{path}: unexpected property {key!r}")
            elif isinstance(extra, dict):
                errors.extend(_errors(child, extra, root, f"{path}.{key}"))
    if isinstance(value, list):
        if schema.get("minItems") is not None and len(value) < int(schema["minItems"]):
            errors.append(f"{path}: expected at least {schema['minItems']} items")
        if schema.get("maxItems") is not None and len(value) > int(schema["maxItems"]):
            errors.append(f"{path}: expected at most {schema['maxItems']} items")
        if schema.get("uniqueItems"):
            rendered = [json.dumps(item, sort_keys=True) for item in value]
            if len(set(rendered)) != len(rendered):
                errors.append(f"{path}: expected unique items")
        items = schema.get("items")
        if isinstance(items, dict):
            for index, item in enumerate(value):
                errors.extend(_errors(item, items, root, f"{path}[{index}]"))
    if isinstance(value, str):
        if schema.get("minLength") is not None and len(value) < int(schema["minLength"]):
            errors.append(f"{path}: expected at least {schema['minLength']} characters")
        if schema.get("pattern") is not None and not re.search(str(schema["pattern"]), value):
            errors.append(f"{path}: does not match pattern {schema['pattern']!r}")
    if isinstance(value, bool):
        return errors
    if isinstance(value, (int, float)):
        if schema.get("minimum") is not None and value < schema["minimum"]:
            errors.append(f"{path}: {value!r} is below minimum {schema['minimum']!r}")
        if schema.get("maximum") is not None and value > schema["maximum"]:
            errors.append(f"{path}: {value!r} is above maximum {schema['maximum']!r}")
        if schema.get("exclusiveMinimum") is not None and value <= schema["exclusiveMinimum"]:
            errors.append(f"{path}: {value!r} is not above exclusiveMinimum {schema['exclusiveMinimum']!r}")
        if schema.get("exclusiveMaximum") is not None and value >= schema["exclusiveMaximum"]:
            errors.append(f"{path}: {value!r} is not below exclusiveMaximum {schema['exclusiveMaximum']!r}")
    return errors


def _is_type(value: object, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    raise AssertionError(f"unsupported schema type in the reviewable subset: {expected!r}")


def validate_against_contract(value: object, contract: dict) -> None:
    errors = _errors(value, contract, contract, "$")
    if errors:
        raise AssertionError("contract violation:\n" + "\n".join(errors))


# ---------------------------------------------------------------------------
# shared fixtures
# ---------------------------------------------------------------------------


_CACHE: dict[str, list[dict]] = {}


def train_rows() -> list[dict]:
    if "train" not in _CACHE:
        rows = model.read_dataset_rows(splits=("TRAIN",))
        _CACHE["train"] = rows if FULL_FIT else rows[::TRAIN_STRIDE]
    return _CACHE["train"]


def validation_rows() -> list[dict]:
    if "validation" not in _CACHE:
        rows = model.read_dataset_rows(splits=("VALIDATION",))
        _CACHE["validation"] = rows if FULL_FIT else rows[::VALIDATION_STRIDE]
    return _CACHE["validation"]


def synthetic_rows(count: int = 900, seed: int = 421) -> list[dict]:
    return model.synthetic_rows(count, seed)


def sample_context() -> dict:
    return {
        "family": "VS_RFI",
        "actor_position": "CO",
        "aggressor_position": "LJ",
        "limper_count": 0,
        "caller_count": 0,
        "live_positions": ["LJ", "HJ", "CO", "BTN", "SB", "BB"],
        "table_size": 6,
        "raise_level": 1,
        "to_call_bb": 3.0,
        "pot_before_bb": 5.5,
        "pot_odds": 0.352941,
        "price_to_pot": 0.545455,
        "effective_stack_bb": 100.0,
    }


class ModelFixtures(unittest.TestCase):
    """Shared, cheap candidates reused by the behavioural tests."""

    @classmethod
    def setUpClass(cls) -> None:
        rows = synthetic_rows()
        cls.rows = rows
        cls.candidates = model.fit_many(
            rows, 421, config=model.make_config(tuning_max_rows=250, holdout_modulus=5)
        )
        cls.regularized = cls.candidates[0]
        cls.hierarchical = cls.candidates[1]


# ---------------------------------------------------------------------------
# contract and dependency surface
# ---------------------------------------------------------------------------


class ContractTests(ModelFixtures):
    def test_contract_is_valid_schema_and_pins_the_module_schema(self) -> None:
        contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        self.assertEqual(contract["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertEqual(
            contract["$id"],
            "https://poker-engine.local/contracts/training/generalized-response-model.schema.json",
        )
        self.assertEqual(contract["$defs"]["candidate"]["properties"]["schema"]["const"], model.SCHEMA)
        self.assertEqual(len(contract["oneOf"]), 6)
        self.assertEqual(
            list(contract["$defs"]["architecture"]["enum"]), list(model.ARCHITECTURES)
        )
        padding = set(contract["$defs"]["prediction"]["required"]) & {
            f"P({action})" for action in model.ACTIONS
        }
        self.assertEqual(len(padding), 4, "the prediction contract must require P(FOLD)..P(JAM)")

    def test_candidates_validate_against_the_contract(self) -> None:
        contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        for candidate in self.candidates:
            validate_against_contract(candidate, contract)
            self.assertEqual(model.validate_candidate(candidate), [])
            prediction = model.predict(candidate, sample_context())
            validate_against_contract(prediction, contract)
            evaluation = model.evaluate(candidate, self.rows[:120])
            validate_against_contract(evaluation, contract)

    def test_price_response_document_validates_against_the_contract(self) -> None:
        contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        response = model.price_response(self.regularized, sample_context(), [2.0, 3.0, 4.0, 5.0])
        validate_against_contract(response, contract)

    def test_comparison_document_validates_against_the_contract(self) -> None:
        contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        comparison = model.compare_candidates(self.candidates, self.rows[:200])
        validate_against_contract(comparison, contract)

    def test_tampered_candidate_is_refused(self) -> None:
        tampered = json.loads(json.dumps(self.regularized))
        tampered["params"]["prior"]["FOLD"] = 0.9
        issues = model.validate_candidate(tampered)
        self.assertTrue(any("prior must sum to 1" in issue for issue in issues), issues)
        self.assertTrue(any("canonical_payload_sha256 does not match" in issue for issue in issues), issues)
        another = json.loads(json.dumps(self.regularized))
        another["params"]["regularization"]["scale"] = -1.0
        self.assertTrue(model.validate_candidate(another))

    def test_persisted_candidate_artifacts_match_their_contract_if_present(self) -> None:
        if not MODEL_DIR.exists():
            self.skipTest("no persisted candidate artifact in this worktree")
        contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        files = sorted(MODEL_DIR.glob("candidate_*.json"))
        self.assertTrue(files, "the persisted model directory has no candidate artifact")
        for path in files:
            candidate = model.load_candidate(path)
            validate_against_contract(candidate, contract)
            self.assertEqual(candidate["canonical_payload_sha256"], model.canonical_candidate_sha256(candidate))
        report_path = MODEL_DIR / "FIT_REPORT.json"
        self.assertTrue(report_path.exists(), "the persisted model directory has no fit report")
        report = json.loads(report_path.read_text(encoding="utf-8"))
        validate_against_contract(report, contract)
        self.assertEqual(report["module_sha256"], model.sha256_bytes(MODULE_PATH.read_bytes()))
        self.assertEqual(report["contract_sha256"], model.sha256_bytes(CONTRACT_PATH.read_bytes()))
        self.assertEqual(
            sorted(entry["architecture"] for entry in report["candidates"]),
            sorted(model.ARCHITECTURES),
        )
        index = json.loads((MODEL_DIR / "ARTIFACTS.json").read_text(encoding="utf-8"))
        for name, entry in index.items():
            payload = (MODEL_DIR / name).read_bytes()
            self.assertEqual(entry["sha256"], model.sha256_bytes(payload), name)
            self.assertEqual(entry["bytes"], len(payload), name)


class DependencySurfaceTests(unittest.TestCase):
    def test_module_imports_only_the_standard_library(self) -> None:
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.level == 0 and node.module:
                    imported.add(node.module.split(".")[0])
        third_party = {"numpy", "scipy", "sklearn", "pandas", "torch", "statsmodels", "joblib"}
        self.assertFalse(imported & third_party, f"third-party import found: {sorted(imported & third_party)}")
        non_stdlib = sorted(name for name in imported if name != "__future__" and name not in sys.stdlib_module_names)
        self.assertEqual(non_stdlib, [], f"non-stdlib imports: {non_stdlib}")

    def test_contract_declares_no_third_party_validator_dependency(self) -> None:
        text = CONTRACT_PATH.read_text(encoding="utf-8")
        self.assertIn("stdlib-validated", text)


# ---------------------------------------------------------------------------
# determinism
# ---------------------------------------------------------------------------


class DeterminismTests(ModelFixtures):
    def test_same_rows_seed_and_config_produce_identical_predictions(self) -> None:
        first = model.fit(self.rows, 7, config=model.make_config(tuning_max_rows=200, holdout_modulus=5))
        second = model.fit(self.rows, 7, config=model.make_config(tuning_max_rows=200, holdout_modulus=5))
        self.assertEqual(first["canonical_payload_sha256"], second["canonical_payload_sha256"])
        for context in (sample_context(), self.rows[0], self.rows[-1]):
            for size in (None, 2.5, 6.0, 11.0):
                query = dict(context)
                if size is not None:
                    query["target_total_bb"] = size
                left = model.predict(first, query)
                right = model.predict(second, query)
                self.assertEqual(left["probabilities"], right["probabilities"])
                self.assertEqual(left["probability_sum"], 1.0)

    def test_fit_is_invariant_to_input_row_order(self) -> None:
        shuffled = list(reversed(self.rows))
        shuffled = shuffled[::3] + shuffled[1::3] + shuffled[2::3]
        straight = model.fit(self.rows, 11, config=model.make_config(tuning_max_rows=200))
        mixed = model.fit(shuffled, 11, config=model.make_config(tuning_max_rows=200))
        self.assertEqual(straight["canonical_payload_sha256"], mixed["canonical_payload_sha256"])

    def test_seed_is_part_of_the_candidate_identity(self) -> None:
        base = model.fit(self.rows, 1, config=model.make_config(tuning_max_rows=150))
        other = model.fit(self.rows, 2, config=model.make_config(tuning_max_rows=150))
        self.assertNotEqual(base["canonical_payload_sha256"], other["canonical_payload_sha256"])
        self.assertEqual(base["seed"], 1)
        self.assertEqual(other["seed"], 2)

    def test_seed_does_not_change_the_legal_normalization_contract(self) -> None:
        for seed in (0, 3, 9):
            candidate = model.fit(self.rows, seed, config=model.make_config(tuning_max_rows=150))
            for row in self.rows[:25]:
                response = model.predict(candidate, row)
                self.assertEqual(response["probability_sum"], 1.0)


# ---------------------------------------------------------------------------
# legal distribution and masking
# ---------------------------------------------------------------------------


class LegalDistributionTests(ModelFixtures):
    def test_distribution_is_legal_and_sums_to_exactly_one(self) -> None:
        for candidate in self.candidates:
            for row in self.rows[:40]:
                response = model.predict(candidate, row)
                self.assertEqual(set(response["probabilities"]), set(model.ACTIONS))
                self.assertEqual(response["probability_sum"], 1.0)
                self.assertEqual(sum(response["probabilities"].values()), 1.0)
                for action, probability in response["probabilities"].items():
                    self.assertGreaterEqual(probability, 0.0, action)
                    self.assertLessEqual(probability, 1.0, action)
                for action in model.ACTIONS:
                    self.assertIn(f"P({action})", response)
                    self.assertEqual(response[f"P({action})"], response["probabilities"][action])
                self.assertEqual(
                    sorted(response["legal_actions"] + response["masked_actions"]), sorted(model.ACTIONS)
                )

    def test_illegal_actions_are_masked_before_normalization(self) -> None:
        context = sample_context()
        context["legal_actions"] = ["FOLD", "CALL"]
        for candidate in self.candidates:
            response = model.predict(candidate, context)
            self.assertEqual(sorted(response["masked_actions"]), ["JAM", "RAISE"])
            self.assertEqual(response["probabilities"]["RAISE"], 0.0)
            self.assertEqual(response["probabilities"]["JAM"], 0.0)
            self.assertEqual(sum(response["probabilities"].values()), 1.0)
            self.assertAlmostEqual(
                response["probabilities"]["FOLD"] + response["probabilities"]["CALL"], 1.0, places=12
            )

    def test_facing_all_in_cannot_raise(self) -> None:
        context = sample_context()
        context["facing_all_in"] = True
        response = model.predict(self.regularized, context)
        self.assertEqual(response["legal_actions"], ["FOLD", "CALL"])
        self.assertEqual(response["probabilities"]["RAISE"], 0.0)
        self.assertEqual(response["probabilities"]["JAM"], 0.0)

    def test_free_check_cannot_call_and_only_live_player_cannot_raise(self) -> None:
        free = sample_context()
        free["to_call_bb"] = 0.0
        free["legal_actions"] = None
        response = model.predict(self.regularized, free)
        self.assertNotIn("CALL", response["legal_actions"])
        self.assertEqual(response["probabilities"]["CALL"], 0.0)
        self.assertEqual(sum(response["probabilities"].values()), 1.0)

        last = sample_context()
        last["live_positions"] = ["CO"]
        response = model.predict(self.regularized, last)
        self.assertEqual(response["legal_actions"], ["FOLD", "CALL"])
        self.assertEqual(response["probabilities"]["RAISE"], 0.0)
        self.assertEqual(response["probabilities"]["JAM"], 0.0)

    def test_derived_mask_matches_the_persisted_dataset_rows(self) -> None:
        """Every persisted row's observed action must be legal under the mask."""
        rows = train_rows()
        sample = rows[:: max(1, len(rows) // 400)][:400]
        for row in sample:
            legal = model.legal_response_actions(row)
            self.assertIn(row["action"], legal, row)
            self.assertEqual(sum(1 for action in model.ACTIONS if action in legal), len(legal))

    def test_uniform_fallback_when_every_legal_weight_vanishes(self) -> None:
        probabilities, mode = model._normalize_legal({"FOLD": 0.0, "CALL": 0.0}, ["FOLD", "CALL"])
        self.assertEqual(mode, "uniform_legal_fallback")
        self.assertEqual(probabilities["FOLD"], 0.5)
        self.assertEqual(probabilities["CALL"], 0.5)
        self.assertEqual(probabilities["RAISE"], 0.0)
        self.assertEqual(sum(probabilities.values()), 1.0)


# ---------------------------------------------------------------------------
# direct price / sizing recalculation
# ---------------------------------------------------------------------------


class PriceSizingTests(ModelFixtures):
    def test_target_total_bb_variation_is_recomputed_directly(self) -> None:
        context = sample_context()
        # Sizes inside the observed sizing support (ratio 0.1 .. 15 of pot+call).
        pot = context["pot_before_bb"] + context["to_call_bb"]
        sizes = [round(pot * ratio, 6) for ratio in (0.2, 0.35, 0.5, 0.65, 0.8, 1.0, 1.2, 1.5, 2.0, 3.0, 5.0)]
        for candidate in self.candidates:
            curve = model.price_response(candidate, context, sizes)
            self.assertTrue(curve["direct_recalculation"])
            self.assertEqual(curve["interpolation"], "linear_spline_partition_of_unity")
            self.assertEqual(curve["distinct_probability_vectors"], len(sizes))
            vectors = [
                tuple(point["probabilities"][action] for action in model.ACTIONS)
                for point in curve["points"]
            ]
            self.assertEqual(len(set(vectors)), len(sizes))
            for point in curve["points"]:
                self.assertEqual(sum(point["probabilities"].values()), 1.0)
            self.assertLess(curve["max_adjacent_probability_jump"], 0.5)

    def test_recalculation_is_not_neighbour_cell_substitution(self) -> None:
        """Two distinct targets inside one spline interval must give distinct outputs."""
        context = sample_context()
        knots = model.SIZING_AXIS
        low, high = knots[2], knots[3]  # ratio 0.5 .. 0.8
        pot = context["pot_before_bb"] + context["to_call_bb"]
        midpoint_a = pot * (low + (high - low) * 0.2)
        midpoint_b = pot * (low + (high - low) * 0.8)
        for candidate in self.candidates:
            first = model.predict(candidate, {**context, "target_total_bb": midpoint_a})
            second = model.predict(candidate, {**context, "target_total_bb": midpoint_b})
            self.assertNotEqual(first["probabilities"], second["probabilities"])
            # Continuity: a small sizing step cannot produce a discontinuity.
            third = model.predict(candidate, {**context, "target_total_bb": midpoint_a + 1e-6})
            for action in model.ACTIONS:
                self.assertLess(abs(third["probabilities"][action] - first["probabilities"][action]), 1e-3)

    def test_default_target_reproduces_the_marginal_distribution(self) -> None:
        context = sample_context()
        pot = context["pot_before_bb"] + context["to_call_bb"]
        reference = pot * model.make_config()["default_target_to_pot_ratio"]
        for candidate in self.candidates:
            marginal = model.predict(candidate, context)
            self.assertEqual(marginal["sizing"]["source"], "default_pot_relative")
            explicit = model.predict(candidate, {**context, "target_total_bb": reference})
            self.assertEqual(explicit["sizing"]["source"], "context")
            for action in model.ACTIONS:
                self.assertAlmostEqual(
                    explicit["probabilities"][action], marginal["probabilities"][action], places=9
                )

    def test_sizing_gain_stays_in_bounds_and_varies_with_the_target(self) -> None:
        context = sample_context()
        pot = context["pot_before_bb"] + context["to_call_bb"]
        low, high = model.make_config()["sizing_gain_bounds"]
        gains = []
        for ratio in (0.3, 0.5, 0.8, 1.2, 2.0, 4.0):
            response = model.predict(self.regularized, {**context, "target_total_bb": pot * ratio})
            gains.append(response["sizing"]["gains"]["RAISE"])
            self.assertGreaterEqual(response["sizing"]["gains"]["RAISE"], low)
            self.assertLessEqual(response["sizing"]["gains"]["JAM"], high)
        self.assertGreaterEqual(len(set(gains)), 3, gains)
        self.assertGreaterEqual(min(gains), low)
        self.assertTrue(
            any(abs(gain - 1.0) < 1e-9 for gain in gains),
            f"the default raise size must be a fixed point of the gain: {gains}",
        )

    def test_current_price_is_a_direct_input_of_the_core_model(self) -> None:
        """A price change moves the discrete-choice core (not only the sizing channel)."""
        cheap = {**sample_context(), "to_call_bb": 1.0, "pot_before_bb": 1.5}
        dear = {**sample_context(), "to_call_bb": 9.0, "pot_before_bb": 16.5}
        for candidate in self.candidates:
            left = model.predict(candidate, cheap)
            right = model.predict(candidate, dear)
            self.assertNotEqual(left["probabilities"], right["probabilities"])
            self.assertEqual(left["sizing"]["source"], "default_pot_relative")
            self.assertAlmostEqual(left["sizing"]["sizing_ratio"], 1.2, places=9)

    def test_evaluation_is_a_function_of_the_queried_sizing(self) -> None:
        rows = [dict(row) for row in self.rows[:60]]
        marginal = model.evaluate(self.regularized, rows, sizing="marginal")
        observed = model.evaluate(self.regularized, rows, sizing="observed_where_available")
        cheap = model.evaluate(self.regularized, rows, target_total_bb=1.0)
        expensive = model.evaluate(self.regularized, rows, target_total_bb=40.0)
        self.assertEqual({report["n"] for report in (marginal, observed, cheap, expensive)}, {len(rows)})
        self.assertEqual(cheap["queried_target_total_bb"], 1.0)
        self.assertEqual(expensive["queried_target_total_bb"], 40.0)
        self.assertIsNone(marginal["queried_target_total_bb"])
        self.assertNotEqual(
            cheap["log_loss_bits_per_decision"], expensive["log_loss_bits_per_decision"]
        )
        self.assertNotEqual(
            marginal["mean_observed_probability"]["RAISE"],
            expensive["mean_observed_probability"]["RAISE"],
        )
        for report in (marginal, observed, cheap, expensive):
            self.assertEqual(report["probability_sum_max_abs_error"], 0.0)
            self.assertEqual(report["illegal_mass_max"], 0.0)
            self.assertLessEqual(report["accuracy"], 1.0)


# ---------------------------------------------------------------------------
# architecture comparison on the persisted dataset
# ---------------------------------------------------------------------------


class ArchitectureComparisonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.train = train_rows()
        cls.validation = validation_rows()
        cls.candidates = model.fit_many(cls.train, 421, config=FAST_CONFIG)
        cls.comparison = model.compare_candidates(cls.candidates, cls.validation)

    def test_both_architectures_train_on_the_same_dataset(self) -> None:
        self.assertEqual([candidate["architecture"] for candidate in self.candidates], list(model.ARCHITECTURES))
        for candidate in self.candidates:
            self.assertEqual(model.validate_candidate(candidate), [])
            self.assertGreater(candidate["fit_summary"]["rows"], 1000)
            self.assertGreater(candidate["fit_summary"]["distinct_hands"], 100)
            self.assertIn("tuning", candidate["fit_summary"])
            self.assertGreaterEqual(candidate["params"]["regularization"]["scale"], 0.0)

    def test_comparison_is_well_formed_and_ranks_both_architectures(self) -> None:
        self.assertEqual(self.comparison["rows"], len(self.validation))
        self.assertEqual(len(self.comparison["ranking"]), 2)
        self.assertIn(self.comparison["best"], self.comparison["ranking"])
        for key, metrics in self.comparison["candidates"].items():
            self.assertEqual(metrics["n"], len(self.validation))
            self.assertGreater(metrics["log_loss_bits_per_decision"], 0.0)
            self.assertEqual(metrics["probability_sum_max_abs_error"], 0.0)
            self.assertEqual(metrics["illegal_mass_max"], 0.0)

    def test_both_architectures_beat_the_global_prior_baseline(self) -> None:
        for key, metrics in self.comparison["candidates"].items():
            self.assertGreater(
                metrics["gain_bits_per_decision"],
                0.0,
                f"{key} does not improve on the global action prior",
            )

    def test_architectures_remain_comparable(self) -> None:
        losses = sorted(metrics["log_loss_bits_per_decision"] for metrics in self.comparison["candidates"].values())
        gap = losses[1] - losses[0]
        self.assertLess(gap, 0.25, f"architectures are not comparable: gap {gap:.4f} bits")

    def test_holdout_fold_is_hand_disjoint(self) -> None:
        for candidate in self.candidates:
            summary = candidate["fit_summary"]
            self.assertEqual(summary["fit_rows"] + summary["holdout_rows"], summary["rows"])
            self.assertGreater(summary["holdout_rows"], 0)
            self.assertEqual(
                summary["holdout_log_loss_bits_per_decision"],
                model.evaluate(candidate, self.holdout_rows_for(candidate))["log_loss_bits_per_decision"],
            )

    def holdout_rows_for(self, candidate: dict) -> list[dict]:
        modulus = int(candidate["config"]["holdout_modulus"])
        seed = int(candidate["seed"])
        return [
            row
            for row in self.train
            if model._holdout_bucket(str(row["hand_id"]), seed, modulus) == 0
        ]

    def test_interaction_budget_is_respected(self) -> None:
        for candidate in self.candidates:
            cap = int(candidate["config"]["interaction_max_cells"])
            for block, cells in candidate["fit_summary"]["interaction_cells"].items():
                self.assertLessEqual(cells, cap, block)


# ---------------------------------------------------------------------------
# persistence, fail-closed behaviour, API wrapper
# ---------------------------------------------------------------------------


class PersistenceTests(ModelFixtures):
    def test_persist_load_roundtrip_is_byte_reproducible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "candidate.json"
            second = Path(directory) / "candidate_again.json"
            metadata_a = model.persist_candidate(self.regularized, first)
            metadata_b = model.persist_candidate(self.regularized, second)
            self.assertEqual(metadata_a["sha256"], metadata_b["sha256"])
            self.assertEqual(metadata_a["bytes"], metadata_b["bytes"])
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(
                metadata_a["canonical_payload_sha256"], self.regularized["canonical_payload_sha256"]
            )
            loaded = model.load_candidate(first)
            self.assertEqual(loaded, self.regularized)
            self.assertEqual(model.validate_candidate(loaded), [])

    def test_persisted_hash_is_detected_when_the_payload_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "candidate.json"
            model.persist_candidate(self.regularized, path)
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["fit_summary"]["rows"] = payload["fit_summary"]["rows"] + 1
            path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
            with self.assertRaises(model.GeneralizedResponseModelError):
                model.load_candidate(path)

    def test_invalid_candidate_is_refused_before_persisting(self) -> None:
        broken = json.loads(json.dumps(self.hierarchical))
        broken["params"]["blocks"].pop("family")
        with self.assertRaises(model.GeneralizedResponseModelError):
            model.persist_candidate(broken, Path(tempfile.gettempdir()) / "never-written.json")

    def test_unknown_config_key_fails_closed(self) -> None:
        with self.assertRaises(model.GeneralizedResponseModelError):
            model.make_config(tuning_max_rowz=10)


class FailClosedTests(ModelFixtures):
    def test_test_split_is_refused_everywhere(self) -> None:
        row = json.loads(json.dumps(self.rows[0]))
        row["split"] = "TEST"
        with self.assertRaises(model.GeneralizedResponseModelError):
            model.fit([row], 0)
        with self.assertRaises(model.GeneralizedResponseModelError):
            model.predict(self.regularized, row)
        with self.assertRaises(model.GeneralizedResponseModelError):
            model.evaluate(self.regularized, [row])
        with self.assertRaises(model.GeneralizedResponseModelError):
            model.read_dataset_rows(splits=("TEST",))

    def test_unknown_split_is_refused(self) -> None:
        row = json.loads(json.dumps(self.rows[0]))
        row["split"] = "HOLDOUT"
        with self.assertRaises(model.GeneralizedResponseModelError):
            model.fit([row], 0)

    def test_action_outside_the_response_space_is_refused(self) -> None:
        row = json.loads(json.dumps(self.rows[0]))
        row["action"] = "CHECK"
        with self.assertRaises(model.GeneralizedResponseModelError):
            model.fit([row], 0)

    def test_unknown_architecture_is_refused(self) -> None:
        with self.assertRaises(model.GeneralizedResponseModelError):
            model.fit(self.rows[:50], 0, architecture="magic")


class ApiWrapperTests(ModelFixtures):
    def test_response_model_wrapper_matches_the_module_api(self) -> None:
        wrapper = model.ResponseModel.fit(
            self.rows, 421, config=model.make_config(tuning_max_rows=200, holdout_modulus=5)
        )
        self.assertEqual(wrapper.canonical_payload_sha256, wrapper.candidate["canonical_payload_sha256"])
        context = sample_context()
        self.assertEqual(wrapper.predict(context), model.predict(wrapper.candidate, context))
        self.assertEqual(wrapper.evaluate(self.rows[:40]), model.evaluate(wrapper.candidate, self.rows[:40]))
        self.assertEqual(
            wrapper.price_response(context, [2.0, 3.0]),
            model.price_response(wrapper.candidate, context, [2.0, 3.0]),
        )

    def test_context_can_be_passed_positionally_or_by_keyword(self) -> None:
        context = sample_context()
        positional = model.predict(self.regularized, context)
        keyword = model.predict(self.regularized, context=context)
        self.assertEqual(positional, keyword)
        with self.assertRaises(model.GeneralizedResponseModelError):
            model.predict(self.regularized, context, unexpected=True)

    def test_self_check_cli_reports_both_architectures(self) -> None:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            exit_code = model.main(["--self-check", "--seed", "5"])
        self.assertEqual(exit_code, 0)
        report = json.loads(buffer.getvalue())
        self.assertEqual([entry["architecture"] for entry in report["candidates"]], list(model.ARCHITECTURES))
        self.assertEqual(len(report["comparison"]["ranking"]), 2)
        for entry in report["candidates"]:
            self.assertAlmostEqual(sum(entry["prediction"].values()), 1.0, places=9)


class RobustnessTests(ModelFixtures):
    def test_single_row_fit_still_returns_a_legal_distribution(self) -> None:
        candidate = model.fit(self.rows[:1], 0, config=model.make_config(tuning_max_rows=10))
        self.assertEqual(candidate["fit_summary"]["rows"], 1)
        response = model.predict(candidate, self.rows[0])
        self.assertEqual(response["probability_sum"], 1.0)
        self.assertEqual(sum(response["probabilities"].values()), 1.0)

    def test_degenerate_action_distribution_stays_legal(self) -> None:
        rows = [dict(row, action="FOLD", target_total_bb=None) for row in self.rows[:200]]
        candidate = model.fit(rows, 0, config=model.make_config(tuning_max_rows=100))
        response = model.predict(candidate, self.rows[5])
        self.assertEqual(response["probability_sum"], 1.0)
        self.assertGreater(response["probabilities"]["FOLD"], 0.9)
        self.assertTrue(all(value >= 0.0 for value in response["probabilities"].values()))

    def test_unseen_categorical_context_does_not_crash(self) -> None:
        unseen = {
            "family": "NEVER_SEEN_FAMILY",
            "actor_position": "ZZ",
            "aggressor_position": "YY",
            "limper_count": 9,
            "caller_count": 9,
            "live_positions": ["BTN", "BB"],
            "table_size": 6,
            "raise_level": 7,
            "to_call_bb": 3.0,
            "pot_before_bb": 5.0,
            "effective_stack_bb": 50.0,
        }
        for candidate in self.candidates:
            response = model.predict(candidate, unseen)
            self.assertEqual(response["probability_sum"], 1.0)
            self.assertEqual(len(response["legal_actions"]), 4)

    def test_price_response_requires_at_least_one_sizing(self) -> None:
        with self.assertRaises(model.GeneralizedResponseModelError):
            model.price_response(self.regularized, sample_context(), [])

    def test_tampered_spline_knots_are_refused(self) -> None:
        broken = json.loads(json.dumps(self.regularized))
        knots = broken["params"]["blocks"]["to_call_bb"]["knots"]
        broken["params"]["blocks"]["to_call_bb"]["knots"] = [knots[0], knots[0]] + knots[2:]
        issues = model.validate_candidate(broken)
        self.assertTrue(any("strictly increasing" in issue for issue in issues), issues)


if __name__ == "__main__":
    unittest.main(verbosity=2)

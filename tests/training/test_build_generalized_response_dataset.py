#!/usr/bin/env python3
"""#421 guard: public-only generalized adverse-response dataset + feature contract.

Covers the four acceptance criteria of the task:

* the dataset is limited to certified TRAIN/VALIDATION and TEST is refused by the
  loader (fail-closed);
* the split is a function of ``hand_id``, so no hand contributes to two folds;
* every row carries strictly public pre-action information (the projection is an
  allowlist; cards, hand classes, history and future state cannot appear);
* rows are adverse (non-Hero) responses whose action lies in the public legal
  action space, and the persisted corpus hashes regenerate byte-identically.

The full byte-identical regeneration of the ~40 MB dataset is opt-in via
``POKER_GENERALIZED_RESPONSE_FULL_REGEN=1`` because it re-parses all certified
hands; the fast path verifies the persisted artifact against its own hashes.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.training import build_generalized_response_dataset as tool  # noqa: E402
from tools.training.fit_model_a_preflop_sizing import load_certified_split  # noqa: E402

FULL_REGEN = os.environ.get("POKER_GENERALIZED_RESPONSE_FULL_REGEN") == "1"

#: Synthetic 6-max hand used to prove the projection is public-only.  Villain2
#: reveals ``Qc Qd`` at showdown and Hero holds ``As Kd``: neither may reach a row.
TRAIN_HAND_ID = "261672888042"
SYNTHETIC_HAND = (
    f"PokerStars Hand #{TRAIN_HAND_ID}: Hold'em No Limit ($1/$2 USD) - 2026/09/26 12:00:00 CET\n"
    "Table 'Test' 6-max Seat #3 is the button\n"
    "Seat 1: Villain1 (200 in chips)\n"
    "Seat 2: Hero (200 in chips)\n"
    "Seat 3: Villain2 (200 in chips)\n"
    "Seat 4: Villain3 (200 in chips)\n"
    "Seat 5: Villain4 (200 in chips)\n"
    "Seat 6: Villain5 (200 in chips)\n"
    "Villain3: posts small blind 1\n"
    "Villain4: posts big blind 2\n"
    "*** HOLE CARDS ***\n"
    "Dealt to Hero [As Kd]\n"
    "Villain5: folds\n"
    "Villain1: raises 4 to 6\n"
    "Hero: folds\n"
    "Villain2: calls 6\n"
    "Villain3: folds\n"
    "Villain4: calls 4\n"
    "*** FLOP *** [2c 7d Jh]\n"
    "Villain2: checks\n"
    "Villain4: checks\n"
    "*** TURN *** [2c 7d Jh] [8s]\n"
    "Villain2: bets 8\n"
    "Villain4: calls 8\n"
    "*** RIVER *** [2c 7d Jh 8s] [3c]\n"
    "Villain2: checks\n"
    "Villain4: checks\n"
    "*** SHOW DOWN ***\n"
    "Villain2: shows [Qc Qd] (a pair of Queens)\n"
    "Villain4: mucked [Th Ts]\n"
    "Villain2 collected 30 from pot\n"
    "*** SUMMARY ***\n"
    "Total pot 30 | Rake 0\n"
)


def _resolve_ref(node: dict, root: dict) -> dict:
    seen = 0
    while "$ref" in node:
        ref = node["$ref"]
        if not ref.startswith("#/"):
            raise AssertionError(f"unsupported $ref: {ref}")
        target: object = root
        for part in ref[2:].split("/"):
            target = target[part]  # type: ignore[index]
        node = target  # type: ignore[assignment]
        seen += 1
        if seen > 16:
            raise AssertionError(f"cyclic $ref: {ref}")
    return node


def validate(value, schema: dict, root: dict, path: str = "$") -> None:
    """Minimal deterministic JSON-Schema checker for the keyword subset used here.

    ``jsonschema`` is not a declared dependency of this repository, so the
    contract is validated with an explicit, reviewable keyword subset.
    """
    schema = _resolve_ref(schema, root)
    if "oneOf" in schema:
        matches = 0
        for candidate in schema["oneOf"]:
            try:
                validate(value, candidate, root, path)
            except AssertionError:
                continue
            matches += 1
        if matches != 1:
            raise AssertionError(f"{path}: expected exactly one oneOf branch, got {matches}")
        return
    if "const" in schema and value != schema["const"]:
        raise AssertionError(f"{path}: expected const {schema['const']!r}, got {value!r}")
    if "enum" in schema and value not in schema["enum"]:
        raise AssertionError(f"{path}: {value!r} not in enum {schema['enum']!r}")
    if "type" in schema:
        expected = schema["type"]
        names = expected if isinstance(expected, list) else [expected]
        ok = False
        for name in names:
            if name == "null" and value is None:
                ok = True
            elif name == "object" and isinstance(value, dict):
                ok = True
            elif name == "array" and isinstance(value, list):
                ok = True
            elif name == "string" and isinstance(value, str):
                ok = True
            elif name == "boolean" and isinstance(value, bool):
                ok = True
            elif name == "integer" and isinstance(value, int) and not isinstance(value, bool):
                ok = True
            elif name == "number" and isinstance(value, (int, float)) and not isinstance(value, bool):
                ok = True
        if not ok:
            raise AssertionError(f"{path}: {type(value).__name__} not in type {names!r}")
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                raise AssertionError(f"{path}: missing required key {key!r}")
        if len(value) < int(schema.get("minProperties", 0)):
            raise AssertionError(f"{path}: fewer than {schema['minProperties']} properties")
        properties = schema.get("properties", {})
        for key, child in value.items():
            if key in properties:
                validate(child, properties[key], root, f"{path}.{key}")
                continue
            if schema.get("additionalProperties") is False:
                raise AssertionError(f"{path}: additional property {key!r} is not allowed")
            extra = schema.get("additionalProperties")
            if isinstance(extra, dict):
                validate(child, extra, root, f"{path}.{key}")
    if isinstance(value, list):
        if len(value) < int(schema.get("minItems", 0)):
            raise AssertionError(f"{path}: fewer than {schema['minItems']} items")
        if schema.get("uniqueItems"):
            if len({json.dumps(x, sort_keys=True) for x in value}) != len(value):
                raise AssertionError(f"{path}: items are not unique")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, child in enumerate(value):
                validate(child, item_schema, root, f"{path}[{index}]")
    if isinstance(value, str):
        if len(value) < int(schema.get("minLength", 0)):
            raise AssertionError(f"{path}: shorter than minLength {schema['minLength']}")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            raise AssertionError(f"{path}: {value!r} does not match {schema['pattern']!r}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            raise AssertionError(f"{path}: {value} < minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            raise AssertionError(f"{path}: {value} > maximum {schema['maximum']}")


class ContractTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = json.loads(tool.CONTRACT_PATH.read_text(encoding="utf-8"))
        cls.index = json.loads((tool.OUTPUT_DIR / tool.INDEX_NAME).read_text(encoding="utf-8"))
        cls.manifest = json.loads((tool.OUTPUT_DIR / tool.MANIFEST_NAME).read_text(encoding="utf-8"))
        cls.corpus = json.loads((tool.OUTPUT_DIR / tool.CORPUS_NAME).read_text(encoding="utf-8"))
        cls.dataset_path = tool.OUTPUT_DIR / tool.DATASET_NAME


class SplitGuardTests(ContractTestBase):
    def test_allowed_splits(self):
        self.assertEqual(tool.require_consumable_splits(("TRAIN", "VALIDATION")), ("TRAIN", "VALIDATION"))
        self.assertEqual(tool.require_consumable_splits(("train",)), ("TRAIN",))

    def test_test_split_is_refused_fail_closed(self):
        for splits in (("TEST",), ("TRAIN", "TEST"), ("VALIDATION", "TEST")):
            with self.assertRaises(tool.TestSplitForbidden):
                tool.require_consumable_splits(splits)

    def test_unknown_split_is_refused(self):
        with self.assertRaises(ValueError):
            tool.require_consumable_splits(("HOLDOUT",))
        with self.assertRaises(ValueError):
            tool.require_consumable_splits(())

    def test_reused_validation_loader_refuses_test(self):
        with self.assertRaises(ValueError):
            load_certified_split("TEST")

    def test_response_iteration_refuses_test(self):
        with self.assertRaises(tool.TestSplitForbidden):
            tool.iter_response_rows([], "TEST")

    def test_persisted_scope_never_consumes_test(self):
        self.assertEqual(self.manifest["scope"]["consumed_splits"], ["TRAIN", "VALIDATION"])
        self.assertEqual(self.manifest["scope"]["refused_splits"], ["TEST"])
        self.assertIs(self.manifest["scope"]["test_consumed"], False)
        self.assertEqual(self.corpus["consumed_splits"], ["TRAIN", "VALIDATION"])
        self.assertEqual(self.corpus["refused_splits"], ["TEST"])
        self.assertEqual(self.corpus["test_hands_consumed"], 0)
        self.assertEqual(self.manifest["accounting"]["total"]["test_hands_consumed"], 0)
        self.assertEqual(
            self.corpus["certified_split_counts"]["TEST"],
            self.corpus["certified_hands"]
            - self.corpus["certified_split_counts"]["TRAIN"]
            - self.corpus["certified_split_counts"]["VALIDATION"],
        )


class ResponseProjectionTests(ContractTestBase):
    def test_action_normalization(self):
        self.assertEqual(tool.response_action("LIMP"), "CALL")
        self.assertEqual(tool.response_action("call"), "CALL")
        self.assertEqual(tool.response_action("FOLD"), "FOLD")
        self.assertEqual(tool.response_action("RAISE"), "RAISE")
        self.assertEqual(tool.response_action("JAM"), "JAM")
        self.assertIsNone(tool.response_action("CHECK"))
        self.assertIsNone(tool.response_action(""))

    def test_aggressor_position_tracks_last_raiser(self):
        history = [
            {"position": "LJ", "action": "RAISE"},
            {"position": "CO", "action": "CALL"},
            {"position": "BTN", "action": "JAM"},
        ]
        self.assertEqual(tool.aggressor_position(history), "BTN")
        self.assertIsNone(tool.aggressor_position([{"position": "LJ", "action": "LIMP"}]))

    def test_synthetic_hand_projects_public_rows_only(self):
        record = type(
            "Record", (), {"hand_id": TRAIN_HAND_ID, "text": SYNTHETIC_HAND, "source_file": "test.txt"}
        )()
        rows, counters = tool.iter_response_rows([record], "TRAIN")
        self.assertEqual(counters["hands_parsed"], 1)
        self.assertEqual(counters["hero_decisions_skipped"], 1)  # Hero folds preflop
        self.assertGreater(counters["non_preflop_decisions_skipped"], 0)
        self.assertGreater(len(rows), 0)
        self.assertTrue(all(row["hand_id"] == TRAIN_HAND_ID for row in rows))
        self.assertTrue(all(row["split"] == "TRAIN" for row in rows))
        self.assertTrue(all(row["action"] in tool.RESPONSE_ACTIONS for row in rows))
        for row in rows:
            self.assertEqual(set(row), set(tool.ROW_FIELDS))
        blob = json.dumps(rows)
        for card in ("As", "Kd", "Qc", "Qd", "Th", "Ts", "2c", "7d", "Jh", "8s", "3c"):
            self.assertNotIn(f'"{card}"', blob)
        raises = [row for row in rows if row["action"] == "RAISE"]
        self.assertTrue(raises)
        self.assertTrue(all(row["target_total_bb"] is not None for row in raises))
        self.assertTrue(all(row["observed_sizing_bb"] is not None for row in raises))
        non_raises = [row for row in rows if row["action"] != "RAISE"]
        self.assertTrue(all(row["target_total_bb"] is None for row in non_raises))
        # The lone adverse raiser is the unraised HJ opener, so every caller
        # faces that opener as the current aggressor.
        self.assertTrue(all(row["aggressor_position"] is None for row in raises))
        callers = [row for row in rows if row["action"] == "CALL"]
        self.assertTrue(callers)
        self.assertEqual(sorted({row["aggressor_position"] for row in callers}), ["HJ"])
        self.assertTrue(all(row["raise_level"] == 1 for row in callers))

    @staticmethod
    def _fake_row(action: str = "RAISE", legal: list[str] | None = None, is_hero: bool = False) -> dict:
        return {
            "hand_id": "1",
            "split": "TRAIN",
            "street": "PREFLOP",
            "is_hero": is_hero,
            "action": action,
            "raise_level": 0,
            "family": "UNOPENED",
            "history": [],
            "action_sizing_v1": {"incremental_cost_bb": 2.0, "target_total_bb": 3.0},
            "preflop_context_v1": {
                "context_id": "PFC_TEST",
                "legal_actions": ["CHECK", "RAISE", "JAM"] if legal is None else legal,
                "table_size": 2,
                "actor_position": "SB_BTN",
                "limper_positions": [],
                "caller_positions": [],
                "live_positions": ["SB_BTN", "BB"],
                "to_call_bb": 0.0,
                "pot_before_bb": 2.0,
                "effective_stack_bb": 100.0,
            },
        }

    def test_public_row_guard_rejects_leaks_and_extra_fields(self):
        valid = {
            "hand_id": "1",
            "split": "TRAIN",
            "table_size": 2,
            "family": "UNOPENED",
            "actor_position": "SB_BTN",
            "aggressor_position": None,
            "limper_count": 0,
            "caller_count": 0,
            "live_positions": ["SB_BTN", "BB"],
            "raise_level": 0,
            "to_call_bb": 0.0,
            "pot_before_bb": 2.0,
            "pot_odds": 0.0,
            "price_to_pot": 0.0,
            "effective_stack_bb": 100.0,
            "target_total_bb": 3.0,
            "observed_sizing_bb": 3.0,
            "action": "RAISE",
        }
        tool.assert_public_row(valid)
        for leak in ({"known_cards": ["As", "Kd"]}, {"known_hand_class": "AKo"}, {"history": []}, {"extra": 1}):
            with self.assertRaises(ValueError):
                tool.assert_public_row({**valid, **leak})
        with self.assertRaises(ValueError):
            tool.assert_public_row({**valid, "action": "CHECK"})
        with self.assertRaises(ValueError):
            tool.assert_public_row({**valid, "split": "TEST"})
        incomplete = dict(valid)
        del incomplete["family"]
        with self.assertRaises(ValueError):
            tool.assert_public_row(incomplete)

    def test_actions_outside_the_legal_space_fail_closed(self):
        legal_raise = self._fake_row("RAISE", ["CHECK", "RAISE", "JAM"])
        self.assertIsNotNone(tool.project_response_row(legal_raise, split="TRAIN"))
        illegal_call = self._fake_row("CALL", ["CHECK", "RAISE", "JAM"])
        with self.assertRaises(tool.IllegalResponseAction):
            tool.project_response_row(illegal_call, split="TRAIN")
        free_check = self._fake_row("CHECK", ["CHECK", "RAISE", "JAM"])
        self.assertIsNone(tool.project_response_row(free_check, split="TRAIN"))
        limp_as_call = self._fake_row("LIMP", ["FOLD", "LIMP"])
        projected = tool.project_response_row(limp_as_call, split="TRAIN")
        self.assertEqual(projected["action"], "CALL")

    def test_hero_and_non_preflop_rows_are_dropped(self):
        hero = self._fake_row("CALL", ["FOLD", "CALL"], is_hero=True)
        self.assertIsNone(tool.project_response_row(hero, split="TRAIN"))
        postflop = self._fake_row("CALL", ["FOLD", "CALL"])
        postflop["street"] = "FLOP"
        self.assertIsNone(tool.project_response_row(postflop, split="TRAIN"))
        wrong_split = self._fake_row("CALL", ["FOLD", "CALL"])
        with self.assertRaises(AssertionError):
            tool.project_response_row(wrong_split, split="VALIDATION")


class PersistedDatasetTests(ContractTestBase):
    def test_artifacts_are_content_addressed(self):
        for name, entry in self.index.items():
            data = (tool.OUTPUT_DIR / name).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), entry["sha256"], name)
            if entry.get("object"):
                self.assertEqual(data, (tool.OUTPUT_DIR / entry["object"]).read_bytes(), name)
        objects = {path.name for path in (tool.OUTPUT_DIR / "sha256").iterdir()}
        self.assertEqual(
            objects,
            {Path(entry["object"]).name for entry in self.index.values() if entry.get("object")},
        )
        self.assertIsNone(self.index[tool.DATASET_NAME]["object"])
        self.assertEqual(self.index[tool.DATASET_NAME]["sha256"], self.manifest["dataset"]["sha256"])
        self.assertEqual(self.index[tool.DATASET_NAME]["bytes"], self.dataset_path.stat().st_size)
        self.assertEqual(
            hashlib.sha256((tool.OUTPUT_DIR / tool.CORPUS_NAME).read_bytes()).hexdigest(),
            self.manifest["corpus"]["sha256"],
            "regenerate with: python3 tools/training/build_generalized_response_dataset.py",
        )
        self.assertEqual(
            hashlib.sha256(tool.CONTRACT_PATH.read_bytes()).hexdigest(),
            self.manifest["contract"]["sha256"],
            "regenerate with: python3 tools/training/build_generalized_response_dataset.py",
        )
        self.assertEqual(
            hashlib.sha256(Path(tool.__file__).resolve().read_bytes()).hexdigest(),
            self.manifest["builder"]["sha256"],
            "regenerate with: python3 tools/training/build_generalized_response_dataset.py",
        )

    def test_contract_parity_with_builder_constants(self):
        row = self.contract["$defs"]["responseRow"]
        self.assertIs(row["additionalProperties"], False)
        self.assertEqual(list(row["required"]), list(tool.ROW_FIELDS))
        self.assertEqual(list(tool.ROW_FIELDS), self.manifest["row_contract"]["fields"])
        self.assertEqual(sorted(tool.FORBIDDEN_ROW_KEYS), self.manifest["row_contract"]["forbidden_keys"])
        self.assertEqual(row["properties"]["action"]["enum"], list(tool.RESPONSE_ACTIONS))
        self.assertEqual(self.contract["$defs"]["splitName"]["enum"], list(tool.SPLITS))
        corpus = self.contract["$defs"]["corpusHashes"]
        self.assertEqual(corpus["properties"]["refused_splits"]["const"], list(tool.FORBIDDEN_SPLITS))
        self.assertEqual(
            corpus["properties"]["certification"]["properties"]["certification_schema"]["const"],
            "poker-population-certification/v1",
        )
        self.assertEqual(
            self.contract["$defs"]["datasetManifest"]["properties"]["schema"]["const"], tool.SCHEMA
        )
        self.assertEqual(corpus["properties"]["schema"]["const"], tool.CORPUS_SCHEMA)
        manifest_schema = self.contract["$defs"]["datasetManifest"]
        self.assertEqual(
            manifest_schema["properties"]["builder"]["properties"]["path"]["const"],
            self.manifest["builder"]["path"],
        )
        self.assertEqual(
            manifest_schema["properties"]["builder"]["properties"]["path"]["const"],
            "tools/training/build_generalized_response_dataset.py",
        )
        self.assertEqual(set(row["properties"]), set(tool.ROW_FIELDS))
        for key in tool.FORBIDDEN_ROW_KEYS:
            self.assertNotIn(key, row["properties"])

    def test_persisted_documents_validate_against_the_contract(self):
        validate(self.manifest, self.contract, self.contract)
        validate(self.corpus, self.contract, self.contract)

    def test_every_persisted_row_is_public_adverse_and_single_fold(self):
        hand_split: dict[str, str] = {}
        split_rows = {"TRAIN": 0, "VALIDATION": 0}
        sample: list[dict] = []
        total = 0
        for index, line in enumerate(self.dataset_path.read_text(encoding="utf-8").splitlines()):
            if not line:
                continue
            row = json.loads(line)
            total += 1
            tool.assert_public_row(row)
            self.assertEqual(sorted(row), sorted(tool.ROW_FIELDS))
            self.assertIn(row["split"], tool.SPLITS)
            self.assertIn(row["action"], tool.RESPONSE_ACTIONS)
            self.assertNotEqual(row["action"], "CHECK")
            self.assertGreaterEqual(row["to_call_bb"], 0.0)
            if row["pot_odds"] is not None:
                self.assertGreaterEqual(row["pot_odds"], 0.0)
                self.assertLessEqual(row["pot_odds"], 1.0)
            if row["action"] in ("FOLD", "CALL"):
                self.assertIsNone(row["target_total_bb"])
                self.assertIsNone(row["observed_sizing_bb"])
            else:
                self.assertIsNotNone(row["target_total_bb"])
                self.assertIsNotNone(row["observed_sizing_bb"])
            seen = hand_split.setdefault(row["hand_id"], row["split"])
            self.assertEqual(seen, row["split"], f"hand {row['hand_id']} spans two folds")
            split_rows[row["split"]] += 1
            if index % 500 == 0:
                sample.append(row)
        self.assertEqual(total, self.manifest["dataset"]["rows"])
        self.assertEqual(total, self.manifest["accounting"]["total"]["response_rows"])
        self.assertEqual(total, self.corpus["response_rows_total"])
        self.assertEqual(split_rows["TRAIN"], self.manifest["splits"]["TRAIN"]["response_rows"])
        self.assertEqual(split_rows["VALIDATION"], self.manifest["splits"]["VALIDATION"]["response_rows"])
        self.assertEqual(split_rows["TRAIN"], self.corpus["response_rows_by_split"]["TRAIN"])
        self.assertEqual(split_rows["VALIDATION"], self.corpus["response_rows_by_split"]["VALIDATION"])
        self.assertGreater(len(hand_split), 0)
        self.assertEqual(len(hand_split), self.manifest["accounting"]["total"]["distinct_hands"])
        self.assertEqual(sum(split_rows.values()), self.manifest["accounting"]["total"]["response_rows"])
        for row in sample:
            validate(row, self.contract["$defs"]["responseRow"], self.contract)

    def test_row_order_is_deterministic(self):
        previous = None
        for line in self.dataset_path.read_text(encoding="utf-8").splitlines():
            if not line:
                continue
            row = json.loads(line)
            key = (int(row["hand_id"]), row["split"])
            if previous is not None:
                self.assertLessEqual(previous, key)
            previous = key

    def test_accounting_is_consistent(self):
        total = self.manifest["accounting"]["total"]
        self.assertEqual(total["hands_loaded"], total["hands_parsed"])
        self.assertEqual(total["distinct_hands"], total["hands_parsed"])
        self.assertEqual(
            total["response_rows"] + total["non_response_action_rows_skipped"],
            total["adverse_preflop_decisions"],
        )
        for split in tool.SPLITS:
            block = self.manifest["splits"][split]
            self.assertEqual(block["hands"], self.corpus["certified_split_counts"][split])
            self.assertEqual(
                block["hand_ids_fingerprint_sha256"],
                self.corpus["loader_evidence"][split]["hand_ids_fingerprint_sha256"],
            )
            self.assertEqual(self.corpus["loader_evidence"][split]["hands"], block["hands"])
            self.assertEqual(self.corpus["loader_evidence"][split]["loader"], tool.LOADER_SOURCES[split])
        self.assertEqual(
            self.corpus["population_fingerprint_sha256"],
            self.manifest["corpus"]["population_fingerprint_sha256"],
        )
        self.assertEqual(
            self.corpus["certification"]["sha256"], self.manifest["corpus"]["certification_sha256"]
        )
        self.assertIn("load_train_records", tool.LOADER_SOURCES["TRAIN"])
        self.assertIn("load_certified_split", tool.LOADER_SOURCES["VALIDATION"])


class DeterminismTests(ContractTestBase):
    def test_payload_serialization_is_deterministic(self):
        rows = [
            {"hand_id": "10", "split": "TRAIN", "action": "FOLD", "b": 1.5, "a": None},
            {"hand_id": "9", "split": "TRAIN", "action": "CALL", "b": 0.0, "a": [1, 2]},
        ]
        first = tool.dataset_payload(rows)
        second = tool.dataset_payload(list(rows))
        self.assertEqual(first, second)
        self.assertEqual(hashlib.sha256(first).hexdigest(), hashlib.sha256(second).hexdigest())
        self.assertTrue(first.endswith(b"\n"))
        self.assertNotIn(b" ", first)

    def test_real_records_regenerate_the_same_bytes(self):
        """Real loaders + real parser over a bounded slice: byte-identical twice."""
        records, _corpus = tool.load_certified_records(("TRAIN", "VALIDATION"))
        subset = {"TRAIN": records["TRAIN"][:120], "VALIDATION": records["VALIDATION"][:40]}
        first_rows, first_accounting = tool.collect_rows(subset, ("TRAIN", "VALIDATION"))
        second_rows, second_accounting = tool.collect_rows(subset, ("TRAIN", "VALIDATION"))
        self.assertEqual(first_accounting, second_accounting)
        self.assertEqual(tool.dataset_payload(first_rows), tool.dataset_payload(second_rows))
        self.assertEqual(first_rows, second_rows)
        self.assertGreater(len(first_rows), 0)
        self.assertTrue(all(row["split"] in tool.SPLITS for row in first_rows))

    def test_declared_slice_mismatch_fails_closed(self):
        records, _corpus = tool.load_certified_records(("TRAIN",))
        with self.assertRaises(AssertionError):
            tool.iter_response_rows(records["TRAIN"][:5], "VALIDATION")

    @unittest.skipUnless(FULL_REGEN, "set POKER_GENERALIZED_RESPONSE_FULL_REGEN=1 to re-parse the corpus")
    def test_full_regeneration_is_byte_identical(self):
        report = tool.verify_persisted(tool.OUTPUT_DIR)
        self.assertTrue(report["byte_identical"])
        self.assertEqual(report["persisted_sha256"], self.manifest["dataset"]["sha256"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

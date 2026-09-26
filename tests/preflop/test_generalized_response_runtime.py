#!/usr/bin/env python3
"""#421 T9 guard: generalized adverse-response runtime provider (fail-closed).

Covers every acceptance criterion of the runtime task:

* the same context and seed always produce the same prediction document, and
  the document is byte-identical under the *pre-3.12* naive ``sum`` semantics
  the frozen model module was fitted with: every float it emits is quantised on
  the runtime's fixed decimal grid and every legal vector is re-closed with
  ``math.fsum``, so the interpreter that ran the raw model answer can never
  move a byte of the surface;
* a variation of the sizing / price is *recomputed directly* through the
  partition-of-unity price/sizing channel -- never a nearest-cell lookup;
* a context outside the calibrated domain (or with a never-observed category)
  abstains: ``OOD_ABSTAIN``, ``usable=false``, no selected action, no sizing;
* illegal actions never receive probability mass and are never selected, and
  every generated RAISE/JAM target is legal;
* the queried raise target is always compared with the engine's legal raise
  window and declared (``sizing_window``): an answerable context whose target
  leaves the window fails closed with ``ILLEGAL_SIZING_GENERATED`` instead of
  being answered through a clamped sizing gain, while an out-of-domain context
  keeps the frozen ``OOD_ABSTAIN`` document and still declares the verdict;
* a candidate / hash mismatch fails closed *before* any evaluation, and the
  document is machine-readable enough for #367 to consume.
"""
from __future__ import annotations

import ast
import builtins
import contextlib
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.preflop import generalized_response_model as model  # noqa: E402
from tools.preflop import generalized_response_runtime as runtime  # noqa: E402
from tools.simulation import issue421_issue367_preflight as preflight_tool  # noqa: E402
from tests.preflop import (  # noqa: E402
    test_generalized_response_sizing as sizing_reference,
)

MODULE_PATH = ROOT / "tools/preflop/generalized_response_runtime.py"
MANIFEST_PATH = ROOT / "analysis/issue421_generalized_response/CANDIDATE_MANIFEST.json"
MODEL_DIR = ROOT / "analysis/issue421_generalized_response/model"
OOD_REPORT_PATH = ROOT / "analysis/issue421_generalized_response/OOD_CALIBRATION_REPORT.json"

#: The provenance value every repository-local resolution must report.
MANIFEST_REGISTRY_SOURCE = "analysis/issue421_generalized_response/CANDIDATE_MANIFEST.json"

PRICE_AXES = {"to_call_bb", "pot_before_bb", "effective_stack_bb"}


def json_string_leaves(node: object, path: str = "$") -> list[tuple[str, str]]:
    """Every string value of a JSON document, addressed by its dotted path."""
    found: list[tuple[str, str]] = []
    if isinstance(node, dict):
        for key, value in node.items():
            found.extend(json_string_leaves(value, f"{path}.{key}"))
            if isinstance(key, str):
                found.append((f"{path}.{key}<key>", key))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            found.extend(json_string_leaves(value, f"{path}[{index}]"))
    elif isinstance(node, str):
        found.append((path, node))
    return found


def float_leaves(node: object, path: tuple = ()) -> list[tuple[tuple, float]]:
    """Every float value of a document, addressed by its structural path."""
    found: list[tuple[tuple, float]] = []
    if isinstance(node, dict):
        for key, value in node.items():
            found.extend(float_leaves(value, path + (key,)))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            found.extend(float_leaves(value, path + (index,)))
    elif isinstance(node, float):
        found.append((path, node))
    return found


def dotted(path: tuple) -> str:
    """A structural path as a readable ``$.a.b[0]`` address."""
    rendered = "$"
    for part in path:
        rendered += f"[{part}]" if isinstance(part, int) else f".{part}"
    return rendered


def quantised(value: object, decimals: int = runtime.CANONICAL_DECIMALS) -> float:
    """The fixed decimal grid, recomputed *here* rather than read off the runtime.

    The expectation side of every canonical assertion is computed with the
    plain, correctly rounded ``round``, so a test can never agree with a broken
    canonicaliser just because both sides called the same helper.  The grid
    itself is taken from the runtime's published constant, which is the
    contract under test.
    """
    number = round(float(value), decimals)  # type: ignore[arg-type]
    return 0.0 if number == 0 else number


def probability_leaf_action(path: tuple) -> str | None:
    """The action a legal-distribution copy leaf belongs to, else ``None``."""
    if len(path) == 2 and path[0] == "probabilities" and path[1] in model.ACTIONS:
        return str(path[1])
    if len(path) == 1 and isinstance(path[0], str) and path[0].startswith("P("):
        return str(path[0])[2:-1]
    return None


def naive_sum(iterable: object, start: object = 0) -> object:
    """CPython <= 3.11's builtin ``sum``: a naive left-to-right float fold."""
    total = start
    for item in iterable:  # type: ignore[union-attr]
        total = total + item  # type: ignore[operator]
    return total


@contextlib.contextmanager
def naive_sum_semantics():
    """Emulate the pre-3.12 ``sum`` semantics for the enclosing block.

    CPython 3.12 replaced the naive float fold with a compensated one, so the
    frozen model module -- whose distribution closure uses the builtin ``sum``
    and which must stay byte-frozen -- can answer a probability whose last bits
    depend on the interpreter that ran it.  The runtime surface has to be
    invariant to that, so this emulation reproduces exactly what 3.9..3.11
    compute for the same operands.
    """
    original = builtins.sum
    builtins.sum = naive_sum
    try:
        yield
    finally:
        builtins.sum = original


def builtin_sum_is_compensated() -> bool:
    """Whether this interpreter's builtin ``sum`` uses the post-3.11 compensated fold.

    ``sum([1.0, 1e100, -1e100])`` is the discriminating probe: the naive
    left-to-right fold loses the ``1.0`` to the huge addend and answers
    ``0.0``, while the compensated fold (CPython 3.12+) answers ``1.0``.  The
    control below only demands an observed perturbation when the running
    interpreter actually *has* something to perturb, so the suite keeps its
    meaning on 3.9..3.14 instead of hard-coding one release.
    """
    return sum([1.0, 1e100, -1e100]) == 1.0


def preflight_probe_contexts() -> list[tuple[str, dict]]:
    """The exact public contexts the #367 preflight queries, from frozen fields.

    Rebuilt with the preflight tool's own constructors -- the required nodes,
    their alternate stack bucket and the frozen raise-sizing frontiers -- so the
    text below tests the same contexts the preflight document reports.
    """
    tree = preflight_tool.load_required_tree()
    tree_nodes = {str(node["id"]): node for node in tree["nodes"]}
    contexts = [
        (f"node:{node['id']}", preflight_tool.node_request_context(node))
        for node in tree["nodes"]
    ]
    contexts += [
        (f"alternate:{node['id']}", preflight_tool.alternate_stack_context(node))
        for node in tree["nodes"]
    ]
    contexts += [
        (
            f"frontier:{frontier['node_id']}",
            preflight_tool.frontier_request_context(frontier, tree_nodes),
        )
        for frontier in model.load_raise_sizing_frontiers()["frontiers"]
    ]
    return contexts


def in_window_probe_contexts() -> list[tuple[str, dict]]:
    """The nine frozen in-window probes of the sizing reference."""
    return [
        (f"in_window:{probe['probe_id']}", probe["context"])
        for probe in sizing_reference.in_window_probes()
    ]


def canonical_probe_contexts() -> list[tuple[str, dict]]:
    """The contexts the interpreter-independence contract is pinned on.

    The runtime's own price probes, the full #367 preflight context set (the
    required nodes, their alternate stack bucket and the frozen raise-sizing
    frontiers) and the nine frozen in-window sizing probes.  The surface has to
    be interpreter-independent on all of them, not on a chosen sample.
    """
    return [
        ("probe:target_3bb", base_context(target_total_bb=3.0)),
        ("probe:default_relative", base_context()),
        ("probe:all_in", base_context(facing_all_in=True)),
        ("probe:no_call_price", base_context(to_call_bb=0.0)),
        ("probe:ood_stack", base_context(effective_stack_bb=5000.0, target_total_bb=3.0)),
    ] + preflight_probe_contexts() + in_window_probe_contexts()


def resolve_probe(
    handle: runtime.GeneralizedResponseRuntime, context: dict, action: str | None = None
) -> tuple[dict | None, str | None]:
    """Resolve one probe: ``(document, None)`` or ``(None, fail_closed_code)``.

    A fail-closed refusal is part of the surface too, so the interpreter
    independence tests compare the refusal code as well as the emitted bytes.
    """
    try:
        return handle.resolve(context, action=action), None
    except runtime.GeneralizedResponseRuntimeError as error:
        return None, error.code


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


def manifest_candidate() -> dict:
    document = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    candidate = document.get("candidate")
    if not isinstance(candidate, dict) or not candidate.get("candidate_id"):
        raise AssertionError("the frozen manifest carries no selected candidate")
    return candidate


class RuntimeFixtures(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not MANIFEST_PATH.exists() or not MODEL_DIR.exists():
            raise unittest.SkipTest("no persisted candidate manifest/artifact in this worktree")
        cls.entry = manifest_candidate()
        cls.candidate_id = str(cls.entry["candidate_id"])
        cls.candidate_sha256 = str(cls.entry["canonical_payload_sha256"])
        runtime.clear_runtime_caches()
        cls.runtime = runtime.GeneralizedResponseRuntime(candidate_id=cls.candidate_id)


# ---------------------------------------------------------------------------
# identity, machine-readable contract and fail-closed loading
# ---------------------------------------------------------------------------


class RuntimeIdentityTests(RuntimeFixtures):
    def test_metadata_binds_the_frozen_candidate_and_calibration(self) -> None:
        metadata = self.runtime.metadata()
        self.assertEqual(metadata["schema"], runtime.PROVIDER_SCHEMA)
        self.assertEqual(metadata["identity"]["candidate_id"], self.candidate_id)
        self.assertEqual(metadata["identity"]["canonical_payload_sha256"], self.candidate_sha256)
        self.assertEqual(self.runtime.candidate_sha256, self.candidate_sha256)
        self.assertEqual(metadata["ood_gate"]["consumed_splits"], ["TRAIN"])
        self.assertEqual(
            metadata["runtime"]["module_sha256"], runtime.sha256_file(MODULE_PATH)
        )
        self.assertTrue(metadata["guarantees"]["fail_closed_on_candidate_hash_mismatch"])
        self.assertTrue(metadata["guarantees"]["direct_price_sizing_evaluation"])

    def test_audit_flags_no_mutation_and_no_split_consumption(self) -> None:
        audit = self.runtime.audit()
        self.assertFalse(audit["active_model_pointer_mutated"])
        self.assertFalse(audit["validation_consumed"])
        self.assertFalse(audit["test_consumed"])
        self.assertFalse(audit["nearest_price"])
        self.assertFalse(audit["nearest_context"])
        self.assertTrue(audit["deterministic"])
        self.assertEqual(sorted(audit["fail_closed_codes"]), sorted(runtime.FAIL_CLOSED_CODES))

    def test_candidate_resolves_by_id_by_hash_and_by_path(self) -> None:
        by_id = runtime.GeneralizedResponseRuntime(candidate_id=self.candidate_id)
        by_hash = runtime.GeneralizedResponseRuntime(expected_candidate_sha256=self.candidate_sha256)
        by_reference = runtime.GeneralizedResponseRuntime(self.candidate_sha256)
        by_path = runtime.GeneralizedResponseRuntime(self.runtime.entry["path"])
        digests = {
            handle.candidate_sha256
            for handle in (by_id, by_hash, by_reference, by_path)
        }
        self.assertEqual(digests, {self.candidate_sha256})
        self.assertEqual(by_hash.entry["candidate_id"], self.candidate_id)
        self.assertEqual(by_path.candidate, by_id.candidate)

    def test_registry_source_is_repo_relative_for_every_resolution_mode(self) -> None:
        expected_artifact = self.runtime.entry["path"]
        handles = {
            "by_id": runtime.GeneralizedResponseRuntime(candidate_id=self.candidate_id),
            "by_hash": runtime.GeneralizedResponseRuntime(self.candidate_sha256),
            "by_expected_hash": runtime.GeneralizedResponseRuntime(
                expected_candidate_sha256=self.candidate_sha256
            ),
            "by_default_id": runtime.GeneralizedResponseRuntime(),
            "by_relative_path": runtime.GeneralizedResponseRuntime(expected_artifact),
            "by_model_directory_path": runtime.GeneralizedResponseRuntime(
                MODEL_DIR / Path(expected_artifact).name
            ),
        }
        for label, handle in handles.items():
            self.assertEqual(handle.entry["registry_source"], MANIFEST_REGISTRY_SOURCE, label)
            self.assertFalse(Path(handle.entry["registry_source"]).is_absolute(), label)
            self.assertEqual(handle.entry["path"], expected_artifact, label)
            self.assertFalse(Path(handle.entry["path"]).is_absolute(), label)
            # No behaviour change: identity and digests are untouched by the
            # provenance normalisation.
            self.assertEqual(handle.entry["candidate_id"], self.candidate_id, label)
            self.assertEqual(handle.candidate_sha256, self.candidate_sha256, label)
            self.assertEqual(
                handle.candidate["canonical_payload_sha256"], self.candidate_sha256, label
            )
            self.assertEqual(
                handle.entry["artifact_sha256"], self.runtime.entry["artifact_sha256"], label
            )

    def test_repo_relative_normalises_paths_without_leaking_the_host(self) -> None:
        self.assertEqual(runtime._repo_relative(MANIFEST_PATH), MANIFEST_REGISTRY_SOURCE)
        self.assertEqual(
            runtime._repo_relative(MANIFEST_REGISTRY_SOURCE), MANIFEST_REGISTRY_SOURCE
        )
        self.assertEqual(
            runtime._repo_relative(MODEL_DIR), "analysis/issue421_generalized_response/model"
        )
        with tempfile.TemporaryDirectory() as folder:
            outside = runtime._repo_relative(Path(folder) / "CANDIDATE_MANIFEST.json")
        self.assertFalse(outside.startswith("/"), outside)
        self.assertNotIn(str(runtime.ROOT), outside)
        self.assertNotIn("\\", outside)

    def test_directory_candidates_report_a_repo_relative_registry_source(self) -> None:
        registry = runtime.candidate_registry()
        directory_candidates = [
            entry for entry in registry.values() if entry.get("role") == "DIRECTORY_CANDIDATE"
        ]
        self.assertTrue(directory_candidates, "the model directory holds candidate artifacts")
        for entry in directory_candidates:
            self.assertEqual(
                entry["registry_source"], "analysis/issue421_generalized_response/model"
            )
            self.assertFalse(Path(entry["registry_source"]).is_absolute())
            self.assertFalse(Path(entry["path"]).is_absolute())

    def test_expected_hash_mismatch_fails_closed_without_evaluating(self) -> None:
        with self.assertRaises(runtime.GeneralizedResponseRuntimeError) as caught:
            runtime.GeneralizedResponseRuntime(
                candidate_id=self.candidate_id,
                expected_candidate_sha256="0" * 64,
            )
        self.assertEqual(caught.exception.code, runtime.FAIL_CLOSED_CANDIDATE_HASH_MISMATCH)
        self.assertIn(self.candidate_sha256, caught.exception.message)

    def test_unknown_candidate_reference_fails_closed(self) -> None:
        for reference in ("not-a-candidate", "f" * 64):
            with self.assertRaises(runtime.GeneralizedResponseRuntimeError) as caught:
                runtime.GeneralizedResponseRuntime(reference)
            self.assertEqual(caught.exception.code, runtime.FAIL_CLOSED_CANDIDATE_NOT_FOUND)

    def test_a_missing_ood_calibration_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            missing = Path(folder) / "OOD_CALIBRATION_REPORT.json"
            with self.assertRaises(runtime.GeneralizedResponseRuntimeError) as caught:
                runtime.GeneralizedResponseRuntime(
                    candidate_id=self.candidate_id, ood_report_path=missing
                )
            self.assertEqual(
                caught.exception.code, runtime.FAIL_CLOSED_CALIBRATION_UNAVAILABLE
            )

    def test_malformed_expected_hash_fails_closed(self) -> None:
        with self.assertRaises(runtime.GeneralizedResponseRuntimeError) as caught:
            runtime.GeneralizedResponseRuntime(
                candidate_id=self.candidate_id, expected_candidate_sha256="abc"
            )
        self.assertEqual(caught.exception.code, runtime.FAIL_CLOSED_CANDIDATE_HASH_MISMATCH)

    def test_tampered_artifact_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "candidate_tampered.json"
            document = json.loads(
                (MODEL_DIR / Path(self.runtime.entry["path"]).name).read_text(encoding="utf-8")
            )
            document["params"]["prior"]["FOLD"] = 0.9
            target.write_text(json.dumps(document, sort_keys=True, indent=2) + "\n", encoding="utf-8")
            with self.assertRaises(runtime.GeneralizedResponseRuntimeError) as caught:
                runtime.GeneralizedResponseRuntime(target)
            self.assertIn(
                caught.exception.code,
                {runtime.FAIL_CLOSED_CANDIDATE_HASH_MISMATCH, runtime.FAIL_CLOSED_CANDIDATE_INVALID},
            )

    def test_inline_candidate_with_a_stale_digest_fails_closed(self) -> None:
        document = json.loads(
            (MODEL_DIR / Path(self.runtime.entry["path"]).name).read_text(encoding="utf-8")
        )
        document["params"]["prior"]["JAM"] = 0.25
        with self.assertRaises(runtime.GeneralizedResponseRuntimeError) as caught:
            runtime.GeneralizedResponseRuntime(document)
        self.assertEqual(caught.exception.code, runtime.FAIL_CLOSED_CANDIDATE_INVALID)

    def test_module_imports_only_the_standard_library(self) -> None:
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                imported.add(node.module.split(".")[0])
        third_party = {"numpy", "scipy", "sklearn", "pandas", "torch", "statsmodels"}
        self.assertFalse(imported & third_party, sorted(imported & third_party))
        # ``tools`` is this repository's own package (the runtime wraps the
        # generalized response model), everything else must be stdlib.
        non_stdlib = sorted(
            name
            for name in imported
            if name not in {"__future__", "tools"} and name not in sys.stdlib_module_names
        )
        self.assertEqual(non_stdlib, [])


# ---------------------------------------------------------------------------
# decision document contract
# ---------------------------------------------------------------------------


class DecisionContractTests(RuntimeFixtures):
    def _decision(self, **overrides: object) -> dict:
        return self.runtime.resolve(base_context(**overrides), action="RAISE")

    def test_decision_document_is_machine_readable(self) -> None:
        document = self._decision(target_total_bb=3.0)
        for key in runtime.RUNTIME_DECISION_REQUIRED_KEYS:
            self.assertIn(key, document, key)
        self.assertEqual(document["schema"], runtime.RUNTIME_SCHEMA)
        self.assertIn(document["status"], runtime.RUNTIME_STATUSES)
        # Round-trippable: the document is plain JSON with no private objects.
        cloned = json.loads(json.dumps(document, sort_keys=True))
        self.assertEqual(cloned, document)
        self.assertEqual(document["context_key"], model.ood_exact_context_key(base_context(target_total_bb=3.0)))
        self.assertEqual(document["deterministic_seed"], int(self.runtime.candidate["seed"]))

    def test_consumer_view_is_self_contained_for_367(self) -> None:
        document = self._decision(target_total_bb=3.0)
        consumer = document["consumer"]
        self.assertEqual(consumer["schema"], runtime.RUNTIME_SCHEMA)
        self.assertEqual(consumer["candidate_id"], self.candidate_id)
        self.assertEqual(consumer["candidate_sha256"], self.candidate_sha256)
        self.assertEqual(consumer["action_space"], list(model.ACTIONS))
        self.assertEqual(consumer["selected_action"], "RAISE")
        self.assertEqual(consumer["illegal_mass"], 0.0)
        self.assertAlmostEqual(consumer["probability_sum"], 1.0, places=9)
        self.assertEqual(consumer["actions"], document["action_probabilities"])
        self.assertEqual(consumer["selected_sizing_bb"], document["selected_sizing_bb"])

    def test_decision_hash_is_canonical_and_recomputable(self) -> None:
        document = self._decision(target_total_bb=3.0)
        self.assertEqual(
            document["decision_canonical_sha256"],
            runtime.decision_canonical_sha256(document),
        )
        self.assertEqual(len(document["decision_canonical_sha256"]), 64)

    def test_the_decision_document_carries_no_absolute_host_path(self) -> None:
        document = runtime.resolve_generalized_response(
            base_context(target_total_bb=3.0), action="RAISE"
        )
        self.assertEqual(
            document["provenance"]["candidate"]["registry_source"], MANIFEST_REGISTRY_SOURCE
        )
        encoded = json.dumps(document, sort_keys=True)
        self.assertNotIn(str(runtime.ROOT), encoded)
        self.assertNotIn("/home/", encoded)
        absolute = [item for item in json_string_leaves(document) if item[1].startswith("/")]
        self.assertEqual(absolute, [])

    def test_provenance_declares_direct_evaluation_and_no_substitution(self) -> None:
        document = self._decision(target_total_bb=3.0)
        prediction = document["prediction"]
        self.assertEqual(document["request"]["evaluation"], "direct_recomputation")
        self.assertEqual(
            prediction["sizing"]["interpolation"], "linear_spline_partition_of_unity"
        )
        self.assertTrue(prediction["sizing"]["conditioned"])
        sizing = document["sizing"]
        self.assertFalse(sizing["nearest_price_substituted"])
        self.assertFalse(sizing["nearest_context_substituted"])
        flags = document["provenance"]["identity_flags"]
        self.assertFalse(flags["nearest_price_substituted"])
        self.assertFalse(flags["nearest_context_substituted"])
        self.assertFalse(flags["active_model_pointer_mutated"])
        self.assertFalse(flags["test_consumed"])
        self.assertFalse(flags["validation_consumed"])

    def test_the_decision_reuses_the_frozen_model_surface_verbatim(self) -> None:
        context = base_context(target_total_bb=3.0)
        candidate = model.load_candidate(MODEL_DIR / Path(self.runtime.entry["path"]).name)
        document = self.runtime.resolve(context, action="RAISE")
        raw = model.predict(candidate, context)
        # The frozen surface is reused verbatim *through the canonical
        # quantiser*: the emitted prediction is exactly the frozen prediction
        # with every float moved onto the runtime's fixed decimal grid, so a
        # mismatch here can only be a canonicalisation defect, never a
        # re-derived distribution.
        self.assertEqual(document["prediction"], runtime.canonical_prediction(raw))
        legal = list(document["legal_actions"])
        # The same statement, recomputed here without calling the runtime's own
        # canonicaliser: every float leaf of the emitted prediction is the
        # *frozen* float on the fixed decimal grid, and the single value that is
        # deliberately off the grid is the one legal action that carries the
        # ``math.fsum`` closure residual.  Nothing is re-derived from another
        # cell, another context or another price.
        frozen_grid = {action: quantised(raw["probabilities"][action]) for action in legal}
        anchor = max(
            legal, key=lambda name: (frozen_grid[name], -model.ACTIONS.index(name))
        )
        for path, value in float_leaves(document["prediction"]):
            action = probability_leaf_action(path)
            if action == anchor:
                expected = document["action_probabilities"][anchor]
            elif action is not None:
                expected = frozen_grid[action] if action in legal else 0.0
            else:
                expected = quantised(value)
            self.assertEqual(value, expected, dotted(path))
            if value != quantised(value):
                # The only off-grid float of the whole prediction is the
                # closure residual of the legal vector, in all of its copies.
                self.assertEqual(action, anchor, dotted(path))
        residual = 1.0 - math.fsum(
            frozen_grid[name] for name in legal if name != anchor
        )
        self.assertLessEqual(
            abs(document["action_probabilities"][anchor] - residual), 4.0 * math.ulp(1.0)
        )
        self.assertEqual(math.fsum(document["action_probabilities"].values()), 1.0)
        # The canonicalisation stays a sub-grid perturbation of the frozen
        # answer -- at most one grid step per quantised sibling, because one
        # legal action carries the ``math.fsum`` closure residual -- so the
        # emitted distribution is the frozen one, never a substitute.
        for action in model.ACTIONS:
            self.assertLessEqual(
                abs(
                    document["action_probabilities"][action]
                    - float(raw["probabilities"][action])
                ),
                len(legal) * 10.0 ** -runtime.CANONICAL_DECIMALS,
                action,
            )
        self.assertEqual(
            document["ood"]["status"],
            model.ood_gate_decision(
                candidate, context, calibration=self.runtime.calibration
            )["status"],
        )
        self.assertEqual(
            document["sizing"]["generated_sizings_bb"],
            model.raise_sizing_query(candidate, context, action="RAISE")["generated_sizings_bb"],
        )

    def test_issue367_consumption_flag_follows_the_frozen_validation_result(self) -> None:
        document = self._decision(target_total_bb=3.0)
        frozen = document["provenance"]["frozen_validation_result"]
        issue367 = document["provenance"]["issue367"]
        self.assertEqual(issue367["rule_id"], runtime.ISSUE367_RULE_ID)
        if frozen.get("available"):
            self.assertEqual(issue367["authorized"], frozen.get("outcome") == "ADMIT_CANDIDATE")
        self.assertFalse(issue367["authorized"], "the runtime must not self-authorize #367 consumption")


# ---------------------------------------------------------------------------
# direct (non-lookup) price / sizing evaluation
# ---------------------------------------------------------------------------


class DirectEvaluationTests(RuntimeFixtures):
    def _probabilities(self, **overrides: object) -> dict:
        document = self.runtime.resolve(base_context(**overrides), action="RAISE")
        self.assertTrue(document["usable"], document["status"])
        return document["action_probabilities"]

    def test_a_sizing_variation_is_recomputed_directly(self) -> None:
        low = self._probabilities(target_total_bb=2.5)["RAISE"]
        middle = self._probabilities(target_total_bb=2.75)["RAISE"]
        high = self._probabilities(target_total_bb=3.0)["RAISE"]
        # A nearest-cell lookup would return one of the two query values exactly.
        self.assertNotEqual(low, middle)
        self.assertNotEqual(middle, high)
        self.assertTrue(high < middle < low, (low, middle, high))
        # The response is continuous: an arbitrarily small move still moves it.
        epsilon = self._probabilities(target_total_bb=3.0001)["RAISE"]
        self.assertLess(epsilon, high)
        self.assertLess(abs(epsilon - high), abs(high - middle))

    def test_a_price_variation_is_recomputed_directly(self) -> None:
        low = self._probabilities(to_call_bb=1.0)["FOLD"]
        middle = self._probabilities(to_call_bb=1.5)["FOLD"]
        high = self._probabilities(to_call_bb=2.0)["FOLD"]
        self.assertNotEqual(low, middle)
        self.assertNotEqual(middle, high)
        self.assertTrue(low < middle < high, (low, middle, high))

    def test_target_is_echoed_and_flips_the_sizing_channel_on(self) -> None:
        default = self.runtime.resolve(base_context(), action="RAISE")
        conditioned = self.runtime.resolve(base_context(target_total_bb=3.0), action="RAISE")
        self.assertEqual(default["request"]["sizing_source"], "default_pot_relative")
        self.assertFalse(default["prediction"]["sizing"]["conditioned"])
        self.assertEqual(conditioned["request"]["sizing_source"], "context")
        self.assertEqual(conditioned["request"]["target_total_bb"], 3.0)
        self.assertEqual(conditioned["request"]["sizing_ratio"], 1.2)
        self.assertTrue(conditioned["prediction"]["sizing"]["conditioned"])
        self.assertNotEqual(
            default["decision_canonical_sha256"], conditioned["decision_canonical_sha256"]
        )

    def test_every_decision_recomputes_the_public_price_axes(self) -> None:
        document = self.runtime.resolve(base_context(target_total_bb=3.0), action="RAISE")
        request = document["request"]
        for axis in PRICE_AXES:
            self.assertIn(axis, request, axis)
            self.assertEqual(request[axis], _round(base_context(target_total_bb=3.0)[axis]))


def _round(value: object, digits: int = runtime.CANONICAL_DECIMALS) -> float:
    """The fixed decimal grid at the request echo's resolution.

    Recomputed with the plain ``round`` rather than read off the runtime, so the
    price-echo assertion in :class:`DirectEvaluationTests` stays an independent
    expectation of the canonical grid.
    """
    return quantised(value, digits)


# ---------------------------------------------------------------------------
# legal action space
# ---------------------------------------------------------------------------


class LegalActionTests(RuntimeFixtures):
    def test_call_is_masked_when_there_is_no_price_to_call(self) -> None:
        document = self.runtime.resolve(base_context(to_call_bb=0.0), action="RAISE")
        self.assertIn("CALL", document["masked_actions"])
        self.assertEqual(document["action_probabilities"]["CALL"], 0.0)
        self.assertNotIn("CALL", document["legal_actions"])
        self.assertAlmostEqual(document["probability_sum"], 1.0, places=9)

    def test_facing_an_all_in_masks_raise_and_jam(self) -> None:
        document = self.runtime.resolve(base_context(facing_all_in=True))
        self.assertEqual(document["masked_actions"], ["RAISE", "JAM"])
        self.assertEqual(document["action_probabilities"]["RAISE"], 0.0)
        self.assertEqual(document["action_probabilities"]["JAM"], 0.0)
        self.assertIn(document["selected_action"], (None, "FOLD", "CALL"))
        self.assertIsNone(document["sizing"])
        with self.assertRaises(runtime.GeneralizedResponseRuntimeError) as caught:
            self.runtime.resolve(base_context(facing_all_in=True), action="JAM")
        self.assertEqual(caught.exception.code, runtime.FAIL_CLOSED_ILLEGAL_ACTION)

    def test_explicit_legal_actions_are_authoritative(self) -> None:
        document = self.runtime.resolve(
            base_context(legal_actions=["FOLD", "CALL"]), action="CALL"
        )
        self.assertEqual(document["legal_actions"], ["FOLD", "CALL"])
        self.assertEqual(document["masked_actions"], ["RAISE", "JAM"])
        self.assertEqual(document["request"]["legal_action_source"], "context.legal_actions")
        self.assertIsNone(document["sizing"])

    def test_an_unknown_action_request_fails_closed(self) -> None:
        with self.assertRaises(runtime.GeneralizedResponseRuntimeError) as caught:
            self.runtime.resolve(base_context(), action="RE_RAISE")
        self.assertEqual(caught.exception.code, runtime.FAIL_CLOSED_ILLEGAL_ACTION)

    def test_a_limp_request_is_the_call_action(self) -> None:
        document = self.runtime.resolve(base_context(), action="LIMP")
        self.assertEqual(document["selected_action"], "CALL")
        self.assertEqual(document["request"]["requested_action"], "LIMP")

    def test_no_decision_ever_carries_illegal_probability_mass(self) -> None:
        for overrides in (
            {},
            {"to_call_bb": 0.0},
            {"facing_all_in": True},
            {"legal_actions": ["FOLD", "CALL"]},
            {"family": "VS_LIMPERS", "actor_position": "BB", "limper_count": 1,
             "live_positions": ["BTN", "SB", "BB"], "to_call_bb": 0.5, "pot_before_bb": 2.5},
        ):
            document = self.runtime.resolve(base_context(**overrides))
            legal = set(document["legal_actions"])
            for action in model.ACTIONS:
                if action not in legal:
                    self.assertEqual(document["action_probabilities"][action], 0.0, (overrides, action))
            self.assertEqual(document["illegal_mass"], 0.0)
            self.assertAlmostEqual(document["probability_sum"], 1.0, places=9)


# ---------------------------------------------------------------------------
# conditional sizing
# ---------------------------------------------------------------------------


class ConditionalSizingTests(RuntimeFixtures):
    def test_a_resolved_raise_returns_legal_generated_sizings(self) -> None:
        document = self.runtime.resolve(base_context(target_total_bb=3.0), action="RAISE")
        sizing = document["sizing"]
        window = sizing["legal_window"]
        self.assertEqual(sizing["status"], "RESOLVED")
        self.assertEqual(sizing["action"], "RAISE")
        self.assertEqual(sizing["illegal_count"], 0)
        self.assertGreater(sizing["generated_count"], 0)
        for target in sizing["generated_sizings_bb"]:
            self.assertGreaterEqual(target, window["floor_bb"] - 1e-9)
            self.assertLessEqual(target, window["cap_bb"] + 1e-9)
        self.assertGreaterEqual(document["selected_sizing_bb"], window["floor_bb"] - 1e-9)
        self.assertLessEqual(document["selected_sizing_bb"], window["cap_bb"] + 1e-9)

    def test_the_explicit_engine_interval_is_authoritative(self) -> None:
        document = self.runtime.resolve(
            base_context(target_total_bb=12.0, min_raise_to_bb=9.0, max_raise_to_bb=60.0),
            action="RAISE",
        )
        window = document["sizing"]["legal_window"]
        self.assertEqual(window["floor_bb"], 9.0)
        self.assertEqual(window["cap_bb"], 60.0)
        self.assertEqual(window["bounds_source"]["min"], "engine_interval")
        for target in document["sizing"]["generated_sizings_bb"]:
            self.assertGreaterEqual(target, 9.0 - 1e-9)
            self.assertLessEqual(target, 60.0 + 1e-9)
        # The queried target is compared with that same window and declared.
        declaration = document["sizing_window"]
        self.assertTrue(declaration["queried"])
        self.assertEqual(declaration["queried_target_bb"], 12.0)
        self.assertTrue(declaration["inside_legal_window"])
        self.assertIsNone(declaration["violation"])
        self.assertEqual(declaration["legal_window"]["floor_bb"], 9.0)
        self.assertEqual(declaration["legal_window"]["cap_bb"], 60.0)

    def test_a_non_aggressive_selection_has_no_sizing_request(self) -> None:
        document = self.runtime.resolve(base_context())
        self.assertEqual(document["selected_action"], "FOLD")
        self.assertIsNone(document["sizing"])
        self.assertIsNone(document["selected_sizing_bb"])

    def test_an_ood_context_never_returns_a_sizing(self) -> None:
        document = self.runtime.resolve(
            base_context(effective_stack_bb=5000.0, target_total_bb=3.0), action="RAISE"
        )
        self.assertEqual(document["status"], runtime.STATUS_ABSTAIN)
        self.assertIsNone(document["sizing"])
        self.assertIsNone(document["selected_sizing_bb"])

    def test_a_blocked_raise_window_is_reported_fail_closed(self) -> None:
        # A raise below the stack is impossible: only the all-in stays legal.
        document = self.runtime.resolve(
            base_context(
                raise_level=1,
                actor_contribution_bb=5.0,
                to_call_bb=30.0,
                pot_before_bb=60.0,
                effective_stack_bb=40.0,
            ),
            action="RAISE",
        )
        if document["usable"]:
            self.assertEqual(document["sizing"]["status"], "FAIL_CLOSED")
            self.assertEqual(
                document["sizing"]["fail_closed_reason"], "RAISE_WINDOW_EMPTY_BELOW_STACK"
            )
            self.assertEqual(document["sizing"]["generated_sizings_bb"], [])
            self.assertIsNone(document["selected_sizing_bb"])


# ---------------------------------------------------------------------------
# queried raise target vs. the engine's legal raise window
# ---------------------------------------------------------------------------


class LegalRaiseWindowTests(RuntimeFixtures):
    """A queried target outside the legal window is declared, never silent.

    Both sides of the window are covered: a target below the engine minimum
    raise and a target beyond the effective-stack cap.  The runtime refuses to
    answer such a request (``ILLEGAL_SIZING_GENERATED``) because an answerable
    context would otherwise be conditioned on a clamped sizing gain, and the
    frozen OOD abstention keeps precedence so a domain refusal is never
    reclassified as a request error.
    """

    def test_a_target_below_the_legal_minimum_fails_closed(self) -> None:
        context = base_context(target_total_bb=5.0, min_raise_to_bb=9.0, max_raise_to_bb=60.0)
        # The model's own window is the authority: 5.0 is below the minimum.
        window = model.raise_sizing_window(context, action="RAISE")
        self.assertFalse(window["fail_closed"])
        self.assertEqual((window["floor_bb"], window["cap_bb"]), (9.0, 60.0))
        with self.assertRaises(runtime.GeneralizedResponseRuntimeError) as caught:
            self.runtime.resolve(context, action="RAISE")
        self.assertEqual(caught.exception.code, runtime.FAIL_CLOSED_ILLEGAL_SIZING)
        self.assertIn(runtime.SIZING_WINDOW_TARGET_BELOW_MINIMUM, caught.exception.message)

    def test_a_target_beyond_the_effective_stack_cap_fails_closed(self) -> None:
        # 100 bb is inside the calibrated sizing domain (ratio 40 < trained max)
        # but beyond the effective stack, i.e. it is not a legal raise target.
        context = base_context(target_total_bb=100.0)
        window = model.raise_sizing_window(context, action="RAISE")
        self.assertEqual(window["cap_bb"], 70.975)
        with self.assertRaises(runtime.GeneralizedResponseRuntimeError) as caught:
            self.runtime.resolve(context, action="RAISE")
        self.assertEqual(caught.exception.code, runtime.FAIL_CLOSED_ILLEGAL_SIZING)
        self.assertIn(runtime.SIZING_WINDOW_TARGET_ABOVE_CAP, caught.exception.message)

    def test_an_in_window_target_is_declared_inside_the_window(self) -> None:
        for target in (2.0, 3.0, 70.975):
            with self.subTest(target=target):
                document = self.runtime.resolve(
                    base_context(target_total_bb=target), action="RAISE"
                )
                declaration = document["sizing_window"]
                self.assertEqual(declaration["schema"], runtime.SIZING_WINDOW_SCHEMA)
                self.assertTrue(declaration["queried"])
                self.assertEqual(declaration["queried_target_bb"], target)
                self.assertTrue(declaration["inside_legal_window"])
                self.assertIsNone(declaration["violation"])
                self.assertFalse(declaration["substituted"])
                self.assertEqual(declaration["policy"], runtime.SIZING_WINDOW_POLICY)
                window = declaration["legal_window"]
                self.assertLessEqual(window["floor_bb"], target)
                self.assertGreaterEqual(window["cap_bb"], target)

    def test_a_context_without_a_queried_target_judges_no_target(self) -> None:
        document = self.runtime.resolve(base_context(), action="RAISE")
        declaration = document["sizing_window"]
        self.assertFalse(declaration["queried"])
        self.assertIsNone(declaration["queried_target_bb"])
        self.assertIsNone(declaration["inside_legal_window"])
        self.assertIsNone(declaration["violation"])
        self.assertEqual(declaration["legal_window"]["floor_bb"], 2.0)

    def test_an_out_of_domain_context_keeps_ood_precedence_and_declares_the_verdict(self) -> None:
        # Far beyond the window *and* beyond the calibrated sizing domain: the
        # frozen OOD abstention is the answer, and the verdict is still stated.
        document = self.runtime.resolve(base_context(target_total_bb=5000.0), action="RAISE")
        self.assertEqual(document["status"], runtime.STATUS_ABSTAIN)
        self.assertFalse(document["usable"])
        self.assertIsNone(document["sizing"])
        declaration = document["sizing_window"]
        self.assertTrue(declaration["queried"])
        self.assertFalse(declaration["inside_legal_window"])
        self.assertEqual(declaration["violation"], runtime.SIZING_WINDOW_TARGET_ABOVE_CAP)

    def test_an_unverifiable_window_is_declared_not_assumed_legal(self) -> None:
        # A non-free regime without the actor's commitment: the model cannot
        # verify the minimum raise, so a queried target is never assumed legal.
        context = base_context(raise_level=2, target_total_bb=3.0)
        declaration = self.runtime.sizing_window_legality(context)
        self.assertTrue(declaration["legal_window"]["fail_closed"])
        self.assertEqual(
            declaration["legal_window"]["fail_closed_reason"],
            "MISSING_MIN_RAISE_TO_UNVERIFIED_COMMITMENT",
        )
        self.assertFalse(declaration["inside_legal_window"])
        self.assertEqual(declaration["violation"], runtime.SIZING_WINDOW_UNVERIFIED)
        with self.assertRaises(runtime.GeneralizedResponseRuntimeError) as caught:
            self.runtime.resolve(context, action="RAISE")
        self.assertEqual(caught.exception.code, runtime.FAIL_CLOSED_ILLEGAL_SIZING)
        self.assertIn(runtime.SIZING_WINDOW_UNVERIFIED, caught.exception.message)


# ---------------------------------------------------------------------------
# OOD / abstention
# ---------------------------------------------------------------------------


class OodAbstentionTests(RuntimeFixtures):
    def test_a_stack_extrapolation_abstains(self) -> None:
        document = self.runtime.resolve(base_context(effective_stack_bb=5000.0), action="RAISE")
        self.assertEqual(document["status"], runtime.STATUS_ABSTAIN)
        self.assertFalse(document["usable"])
        self.assertTrue(document["abstain"])
        self.assertTrue(document["fail_closed"])
        self.assertEqual(document["fail_closed_reason"], runtime.OOD_ABSTAIN_REASON)
        self.assertIn("EXTRAPOLATION_STACK", document["ood"]["hard_reasons"])
        self.assertIsNone(document["selected_action"])
        self.assertIsNone(document["sizing"])
        # The distribution is still reported, for diagnostics only.
        self.assertAlmostEqual(document["probability_sum"], 1.0, places=9)

    def test_a_sizing_extrapolation_abstains(self) -> None:
        document = self.runtime.resolve(base_context(target_total_bb=5000.0), action="RAISE")
        self.assertEqual(document["status"], runtime.STATUS_ABSTAIN)
        self.assertIn("EXTRAPOLATION_SIZING", document["ood"]["hard_reasons"])

    def test_a_never_observed_category_abstains(self) -> None:
        document = self.runtime.resolve(base_context(family="NOT_A_FAMILY"), action="RAISE")
        self.assertEqual(document["status"], runtime.STATUS_ABSTAIN)
        self.assertIn("UNSEEN_CATEGORY", document["ood"]["hard_reasons"])
        self.assertIsNone(document["selected_action"])

    def test_a_missing_domain_axis_abstains(self) -> None:
        context = base_context()
        context.pop("pot_before_bb")
        document = self.runtime.resolve(context)
        self.assertEqual(document["status"], runtime.STATUS_ABSTAIN)
        self.assertIn("MISSING_DOMAIN_AXIS", document["ood"]["hard_reasons"])

    def test_a_high_uncertainty_context_stays_usable(self) -> None:
        document = self.runtime.resolve(
            base_context(
                family="VS_LIMPERS",
                actor_position="BB",
                limper_count=1,
                live_positions=["BTN", "SB", "BB"],
                to_call_bb=0.5,
                pot_before_bb=2.5,
                effective_stack_bb=100.0,
            )
        )
        self.assertEqual(document["status"], runtime.STATUS_HIGH_UNCERTAINTY)
        self.assertTrue(document["usable"])
        self.assertFalse(document["fail_closed"])
        self.assertIsNotNone(document["selected_action"])

    def test_ood_abstention_is_excluded_from_the_consumer_view(self) -> None:
        document = self.runtime.resolve(base_context(effective_stack_bb=5000.0), action="RAISE")
        consumer = document["consumer"]
        self.assertFalse(consumer["usable"])
        self.assertEqual(consumer["status"], runtime.STATUS_ABSTAIN)
        self.assertIsNone(consumer["selected_action"])
        self.assertIsNone(consumer["selected_sizing_bb"])


# ---------------------------------------------------------------------------
# interpreter independence (the canonical numeric surface)
# ---------------------------------------------------------------------------


class CanonicalSurfaceTests(RuntimeFixtures):
    """The runtime surface, not the interpreter, decides the emitted bytes.

    The frozen model closes its distribution with the builtin ``sum``, whose
    float semantics changed in CPython 3.12.  These tests drive the *same*
    contexts through the pre-3.12 naive summation semantics and pin the two
    exactness invariants the #367 consumer relies on -- ``probability_sum`` is
    exactly ``1.0`` and ``illegal_mass`` is exactly ``0.0`` -- plus the fixed
    decimal grid every emitted float is anchored on.
    """

    def test_the_document_is_byte_identical_under_naive_sum_semantics(self) -> None:
        contexts = canonical_probe_contexts()
        self.assertGreaterEqual(len(contexts), 50, "the preflight context set is walked")
        for label, context in contexts:
            for action in (None, "RAISE"):
                with self.subTest(context=label, action=action):
                    native, native_code = resolve_probe(self.runtime, context, action)
                    with naive_sum_semantics():
                        naive, naive_code = resolve_probe(
                            runtime.GeneralizedResponseRuntime(candidate_id=self.candidate_id),
                            context,
                            action,
                        )
                    # A fail-closed refusal is part of the surface: the same
                    # request must fail closed with the same code.
                    self.assertEqual(native_code, naive_code, (label, action))
                    if native_code is not None:
                        self.assertIsNone(native)
                        self.assertIsNone(naive)
                        continue
                    self.assertIsNotNone(native)
                    self.assertIsNotNone(naive)
                    # Byte identity, not a tolerance: the JSON encoding of the
                    # whole document and its canonical digest must agree.
                    self.assertEqual(
                        json.dumps(native, sort_keys=True), json.dumps(naive, sort_keys=True)
                    )
                    self.assertEqual(
                        native["decision_canonical_sha256"],
                        naive["decision_canonical_sha256"],
                    )
                    self.assertEqual(
                        native["action_probabilities"], naive["action_probabilities"]
                    )

    def test_probability_sum_and_illegal_mass_are_exact(self) -> None:
        for label, context in preflight_probe_contexts() + in_window_probe_contexts():
            document = self.runtime.resolve(context)
            with self.subTest(context=label):
                self.assertEqual(document["probability_sum"], 1.0)
                self.assertEqual(document["illegal_mass"], 0.0)
                self.assertEqual(math.fsum(document["action_probabilities"].values()), 1.0)
                legal = set(document["legal_actions"])
                for action in model.ACTIONS:
                    if action not in legal:
                        self.assertEqual(document["action_probabilities"][action], 0.0, action)
                # The embedded copies of the distribution are the same vector,
                # never a second (interpreter-dependent) computation of it.
                self.assertEqual(
                    document["prediction"]["probabilities"], document["action_probabilities"]
                )
                self.assertEqual(document["prediction"]["probability_sum"], 1.0)
                self.assertEqual(
                    document["consumer"]["actions"], document["action_probabilities"]
                )
                self.assertEqual(document["consumer"]["probability_sum"], 1.0)
                self.assertEqual(document["consumer"]["illegal_mass"], 0.0)
                for action in model.ACTIONS:
                    self.assertEqual(
                        document["prediction"][f"P({action})"],
                        document["action_probabilities"][action],
                        action,
                    )

    def test_the_queried_context_and_price_are_never_substituted(self) -> None:
        for label, context in preflight_probe_contexts() + in_window_probe_contexts():
            document = self.runtime.resolve(context)
            with self.subTest(context=label):
                # The context key is the queried context's own key and the
                # request echo is the queried price, quantised -- never a
                # neighbouring observation, a bucket representative or a
                # clamped substitute.
                self.assertEqual(document["context_key"], model.ood_exact_context_key(context))
                query = model.sizing_context(context, self.runtime.candidate["config"])
                for axis in ("pot_before_bb", "to_call_bb"):
                    self.assertEqual(
                        document["request"][axis], runtime.canonical_float(query[axis]), axis
                    )
                self.assertEqual(
                    document["request"]["effective_stack_bb"],
                    runtime.canonical_float(context["effective_stack_bb"]),
                )
                self.assertEqual(
                    document["sizing_window"]["queried_target_bb"],
                    None
                    if context.get("target_total_bb") is None
                    else runtime.canonical_float(context["target_total_bb"]),
                )
                self.assertFalse(document["sizing_window"]["substituted"])
                flags = document["provenance"]["identity_flags"]
                self.assertFalse(flags["nearest_price_substituted"])
                self.assertFalse(flags["nearest_context_substituted"])

    def test_the_selected_action_follows_the_emitted_distribution(self) -> None:
        for label, context in preflight_probe_contexts() + in_window_probe_contexts():
            document = self.runtime.resolve(context)
            with self.subTest(context=label):
                if not document["usable"]:
                    self.assertIsNone(document["selected_action"])
                    continue
                emitted = document["action_probabilities"]
                expected = max(
                    document["legal_actions"],
                    key=lambda name: (emitted[name], -model.ACTIONS.index(name)),
                )
                self.assertEqual(document["selected_action"], expected)

    def test_every_emitted_float_is_anchored_on_the_fixed_grid(self) -> None:
        stride = 10.0 ** -runtime.CANONICAL_DECIMALS
        for label, context in canonical_probe_contexts():
            for action in (None, "RAISE"):
                with self.subTest(context=label, action=action):
                    document, code = resolve_probe(self.runtime, context, action)
                    if code is not None:
                        self.assertIsNone(document)
                        continue
                    self.assertIsNotNone(document)
                    leaves = float_leaves(document)
                    self.assertGreater(len(leaves), 40)
                    emitted = document["action_probabilities"]
                    legal = list(document["legal_actions"])
                    anchor = max(
                        legal, key=lambda name: (emitted[name], -model.ACTIONS.index(name))
                    )
                    for path, value in leaves:
                        # Every float the document emits was quantised on the
                        # fixed grid by the one canonical pass ...
                        self.assertLessEqual(
                            abs(value - quantised(value)), stride, dotted(path)
                        )
                        if value != quantised(value):
                            # ... and the single exception is the copy of the
                            # closure residual that keeps the legal vector an
                            # exact partition of unity.
                            self.assertIn(path[-1], (anchor, f"P({anchor})"), dotted(path))
                            self.assertEqual(value, emitted[anchor], dotted(path))

    def test_the_interpreter_perturbation_never_crosses_a_grid_cell(self) -> None:
        """The byte identity is a property of the grid, not a coincidence.

        The frozen model closes its distribution with the builtin ``sum``, so
        the same context can answer a probability whose last bits depend on the
        interpreter.  Quantising on the fixed decimal grid can only absorb that
        perturbation while the frozen value stays clear of a cell boundary:
        these tests measure the distance to the nearest boundary and the size of
        the perturbation itself, and require the first to dominate the second by
        an order of magnitude on every float of the frozen prediction.

        The measurement is also a control on the emulation itself: on an
        interpreter whose builtin ``sum`` is already the naive fold (3.9..3.11)
        there is nothing to perturb, but on a compensated one (3.12+) the
        emulation must actually move at least one frozen float -- otherwise the
        byte-identity test above would be proving a tautology.
        """
        stride = 10.0 ** -runtime.CANONICAL_DECIMALS
        tightest = math.inf
        perturbed = 0
        for label, context in canonical_probe_contexts():
            native = float_leaves(self.runtime.predict(context))
            with naive_sum_semantics():
                emulated = float_leaves(
                    runtime.GeneralizedResponseRuntime(
                        candidate_id=self.candidate_id
                    ).predict(context)
                )
            with self.subTest(context=label):
                self.assertEqual([path for path, _ in native], [path for path, _ in emulated])
                for (path, value), (_, other) in zip(native, emulated):
                    # Both summation semantics quantise into the same cell ...
                    self.assertEqual(quantised(value), quantised(other), dotted(path))
                    # ... because the frozen value sits well inside its cell.
                    scaled = value / stride
                    margin = abs(scaled - math.floor(scaled) - 0.5) * stride
                    delta = abs(value - other)
                    if delta > 0.0:
                        perturbed += 1
                        tightest = min(tightest, margin / delta)
        if builtin_sum_is_compensated():
            self.assertGreater(
                perturbed,
                0,
                "the naive-sum emulation moved no frozen float: the "
                "interpreter-independence test is vacuous on this candidate",
            )
        # Measured at ~2.3e2 on the frozen candidate; the order of magnitude is
        # what makes the contract hold on 3.9..3.14 and not only between the two
        # summation semantics emulated here.
        self.assertGreaterEqual(tightest, 10.0, tightest)

    def test_the_canonical_helper_absorbs_a_one_ulp_perturbation(self) -> None:
        raw = self.runtime.predict(base_context(target_total_bb=3.0))
        legal = list(raw["legal_actions"])
        vector, probability_sum, illegal_mass = runtime.canonical_legal_distribution(
            raw["probabilities"], legal
        )
        self.assertEqual(probability_sum, 1.0)
        self.assertEqual(illegal_mass, 0.0)
        self.assertEqual(math.fsum(vector.values()), 1.0)
        for direction in (math.inf, -math.inf):
            perturbed = {
                action: math.nextafter(value, direction)
                for action, value in raw["probabilities"].items()
            }
            with self.subTest(direction=direction):
                self.assertEqual(
                    runtime.canonical_legal_distribution(perturbed, legal), (vector, 1.0, 0.0)
                )

    def test_the_document_canonicalisation_is_idempotent(self) -> None:
        for action in (None, "RAISE"):
            document = self.runtime.resolve(base_context(target_total_bb=3.0), action=action)
            self.assertEqual(runtime.canonicalize_decision_document(document), document)


# ---------------------------------------------------------------------------
# determinism and split / seed guards
# ---------------------------------------------------------------------------


class DeterminismTests(RuntimeFixtures):
    def test_same_context_and_seed_are_byte_identical(self) -> None:
        contexts = (
            base_context(),
            base_context(target_total_bb=3.0),
            base_context(to_call_bb=2.0, pot_before_bb=4.0, effective_stack_bb=60.0),
            base_context(family="VS_LIMPERS", actor_position="BB", limper_count=1,
                         live_positions=["BTN", "SB", "BB"], to_call_bb=0.5, pot_before_bb=2.5),
        )
        for context in contexts:
            for action in (None, "RAISE", "JAM"):
                first = resolve(context, action)
                second = resolve(context, action)
                self.assertEqual(
                    json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True), (context, action)
                )
                self.assertEqual(
                    first["decision_canonical_sha256"], second["decision_canonical_sha256"]
                )

    def test_the_seed_is_part_of_the_request_identity(self) -> None:
        pinned = int(self.runtime.candidate["seed"])
        accepted = self.runtime.resolve(base_context(), seed=pinned)
        self.assertEqual(accepted["deterministic_seed"], pinned)
        with self.assertRaises(runtime.GeneralizedResponseRuntimeError) as caught:
            self.runtime.resolve(base_context(), seed=pinned + 1)
        self.assertEqual(caught.exception.code, runtime.FAIL_CLOSED_SEED_MISMATCH)

    def test_a_test_split_context_is_never_consumed(self) -> None:
        with self.assertRaises(runtime.GeneralizedResponseRuntimeError) as caught:
            self.runtime.resolve(base_context(split="TEST"))
        self.assertEqual(caught.exception.code, runtime.FAIL_CLOSED_TEST_SPLIT)


def resolve(context: dict, action: str | None, seed: int | None = None) -> dict:
    """Resolve through the module-level entry point (fresh handle per call)."""
    return runtime.GeneralizedResponseRuntime(candidate_id=manifest_candidate()["candidate_id"]).resolve(
        context, action=action, seed=seed
    )


if __name__ == "__main__":
    unittest.main(verbosity=2)

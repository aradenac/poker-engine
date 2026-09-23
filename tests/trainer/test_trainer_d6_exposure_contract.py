#!/usr/bin/env python3
"""#393 T5 — source-of-truth + D6 exposure guard for the Training preflop surface.

This is the static/content contract that pins the #393 semantic boundary against
regression. It proves three independent invariants:

1. **Every Hero recommendation/EV exposure path in ``site/trainer.js`` is gated
   by the canonical D6 rule** (``trainerPreflopDecisionView().show_ev``, i.e.
   ``admissible && comparable``) and **never** by a legacy covered-only gate
   (``PokerPreflopRuntime.isCovered`` / a local ``covered``/``coverage_state ===
   "COVERED"`` recombination).

   The guard is built from an explicit registry of every preflop exposure path.
   It also *scans the whole file* so a new function that touches the preflop
   decision payload without being registered with a gate fails the contract.
   That scan is what makes "gated only by covered/isCovered" impossible to merge.

2. **No local D6 rule duplicates the canonical derivation.** The literal rule
   ``show_ev:admissible&&comparable`` exists exactly once, in
   ``trainerPreflopDecisionView``, which itself delegates to
   ``trainerPreflopAnalysis`` -> ``PokerAnalysisState.mapAnalysisState``. The
   only other function allowed to read both separated dimensions is the strictly
   secondary technical panel (``trainerAnalysisDimensionsHtml``), which formats
   them without recombining them into a gate.

3. **``src/analytics/analysis-state.js`` and ``site/analytics/analysis-state.js``
   stay byte-identical**, and the dedicated analysis-state CI workflow keeps
   executing the parity guard. The canonical taxonomy semantics are asserted
   unchanged (six states, ``NOT_EVALUATED`` dimensions, D5/D6 rules, statistical
   support counters).

Paths whose gate cannot be decided statically (e.g. ``trainerRenderControls``
reads the already-sanitized ``trainerState.recommendation.bestCostBB``) are
asserted **at runtime** through the canonical detail derivation below and are
cross-referenced to the T4 D6 render matrix
(``test_d6_render_matrix_contract.py`` / ``smoke_trainer_d6_render_matrix.py`` /
``fixtures/d6_render_matrix.json``), which drives the real assembled app.

No model/fit and no canonical taxonomy behaviour is modified by this contract.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TRAINER_PATH = ROOT / "site" / "trainer.js"
TRAINER = TRAINER_PATH.read_text(encoding="utf-8")
INDEX = (ROOT / "site" / "index.html").read_text(encoding="utf-8")

SOURCE = ROOT / "src" / "analytics" / "analysis-state.js"
MIRROR = ROOT / "site" / "analytics" / "analysis-state.js"
SCHEMA_PATH = ROOT / "contracts" / "analytics" / "analysis-state.schema.json"
DOC_PATH = ROOT / "docs" / "analysis-state-contract.md"

ANALYSIS_WORKFLOW_PATH = ROOT / ".github" / "workflows" / "analysis-state-contract.yml"
TRAINER_WORKFLOW_PATH = ROOT / ".github" / "workflows" / "trainer-smoke.yml"

D6_CONTRACT = ROOT / "tests" / "trainer" / "test_d6_render_matrix_contract.py"
D6_DRIVER = ROOT / "tests" / "trainer" / "smoke_trainer_d6_render_matrix.py"
D6_FIXTURE = ROOT / "tests" / "trainer" / "fixtures" / "d6_render_matrix.json"

SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
DOC = DOC_PATH.read_text(encoding="utf-8")
ANALYSIS_WORKFLOW = ANALYSIS_WORKFLOW_PATH.read_text(encoding="utf-8")
TRAINER_WORKFLOW = TRAINER_WORKFLOW_PATH.read_text(encoding="utf-8")

NODE = shutil.which("node")

# The canonical six states. Pinned here as a non-regression net so a test edit
# cannot silently rename/remove a state while "keeping the suite green".
CANONICAL_STATES = [
    "ANALYSE_DISPONIBLE",
    "ANALYSE_PARTIELLE",
    "CALCUL_EN_COURS",
    "DONNEES_INSUFFISANTES",
    "SPOT_NON_SUPPORTE",
    "ERREUR_CALCUL",
]

# Raw Hero fields carried by the ``poker-preflop-decision/v1`` payload. These are
# the fields D6 forbids when the gate is closed.
RAW_PREFLOP_EV_FIELDS = (
    "recommended_ev_bb",
    "played_ev_bb",
    "recommended_target_sizing",
    "incremental_cost_bb",
)
RAW_PREFLOP_ACTION_FIELDS = ("recommended_action",)

# Derived Hero fields produced/consumed by the Trainer detail/record layer. They
# are D6-gated too because they are computed from the raw preflop fields.
DERIVED_HERO_FIELDS = ("bestEV", "chosenEV", "bestLabel", "bestCostBB", "lossBB")


def strip_js_comments(text: str) -> str:
    """Remove ``//`` and ``/* */`` comments, respecting string/template literals.

    The comment fixtures in trainer.js legitimately mention ``isCovered`` /
    ``ev_comparable``; the contract must judge *code*, not prose, so the analysis
    runs on the comment-stripped source.
    """
    out: list[str] = []
    i = 0
    n = len(text)
    quote: str | None = None
    while i < n:
        char = text[i]
        if quote is None:
            if char == "/" and i + 1 < n and text[i + 1] == "/":
                newline = text.find("\n", i)
                if newline < 0:
                    break
                i = newline
                continue
            if char == "/" and i + 1 < n and text[i + 1] == "*":
                closing = text.find("*/", i + 2)
                i = n if closing < 0 else closing + 2
                continue
            if char in ("'", '"', "`"):
                quote = char
                out.append(char)
                i += 1
                continue
            out.append(char)
            i += 1
        else:
            out.append(char)
            if char == "\\":
                if i + 1 < n:
                    out.append(text[i + 1])
                    i += 2
                    continue
            elif char == quote:
                quote = None
            i += 1
    return "".join(out)


def function_bodies(text: str) -> dict[str, str]:
    """Return ``{function_name: body_including_braces}`` using brace matching."""
    bodies: dict[str, str] = {}
    for match in re.finditer(r"(?:^|\n)(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(", text):
        name = match.group(1)
        i = text.index("(", match.end() - 1)
        depth = 0
        while i < len(text):
            char = text[i]
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        start = text.index("{", i)
        depth = 0
        end = start
        while end < len(text):
            char = text[end]
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    break
            end += 1
        bodies[name] = text[start : end + 1]
    return bodies


CODE = strip_js_comments(TRAINER)
BODIES = function_bodies(CODE)

# ---------------------------------------------------------------------------
# The explicit registry of every preflop recommendation/EV exposure path.
#
# ``kind`` is the canonical gate the function must use:
#   * ``show_ev``   -> must reference the canonical ``show_ev`` gate; may only
#                      expose the recommendation/EV once D6 is open;
#   * ``admissible``-> exposes only the recommended *action kind* for guided
#                      targeting, gated on the admissibility half of D6 (the EV
#                      and sizing stay behind ``show_ev``);
#   * ``compute``   -> builds the detail via ``trainerDetailFromPreflopDecision``
#                      and must not itself recombine D6.
#
# ``raw_fields`` lists the preflop fields the function may touch, used for the
# "canonical view derived before any raw field" ordering proof.
# ---------------------------------------------------------------------------
D6_EXPOSURE_REGISTRY: dict[str, dict] = {
    "trainerDetailFromPreflopDecision": {
        "kind": "show_ev",
        "raw_fields": RAW_PREFLOP_EV_FIELDS + RAW_PREFLOP_ACTION_FIELDS,
    },
    "trainerDecisionClass": {"kind": "show_ev", "raw_fields": ()},
    "trainerRecordDecision": {"kind": "show_ev", "raw_fields": ("ev_comparable",)},
    "trainerRecommendationKind": {
        "kind": "admissible",
        "raw_fields": RAW_PREFLOP_ACTION_FIELDS,
    },
    "trainerGuidedClickCost": {
        "kind": "show_ev",
        "raw_fields": RAW_PREFLOP_EV_FIELDS + RAW_PREFLOP_ACTION_FIELDS,
    },
    "trainerReuseBestAsPlayed": {"kind": "show_ev", "raw_fields": ()},
    "trainerPreflopDecisionSummaryHtml": {
        "kind": "show_ev",
        "raw_fields": RAW_PREFLOP_EV_FIELDS + RAW_PREFLOP_ACTION_FIELDS + ("ev_comparable",),
    },
    "trainerBestText": {"kind": "show_ev", "raw_fields": ()},
    "trainerRenderRecommendation": {
        "kind": "show_ev",
        "raw_fields": RAW_PREFLOP_EV_FIELDS + RAW_PREFLOP_ACTION_FIELDS,
    },
    "trainerRenderFeedback": {"kind": "show_ev", "raw_fields": ("ev_comparable",)},
    # Not a display path: it builds the canonical detail through the gated
    # derivation and must not duplicate the rule locally.
    "trainerComputePreflopReference": {"kind": "compute", "raw_fields": ()},
}

# The single canonical derivation is checked outside the registry because it
# *is* the D6 rule; everything else must go through it.
DERIVATION_FUNCTION = "trainerPreflopDecisionView"
# The strictly secondary technical panel may read both separated dimensions to
# format them, but must never recombine them into an admissibility gate.
TECHNICAL_PANEL_FUNCTION = "trainerAnalysisDimensionsHtml"

D6_RULE_LITERAL = "show_ev:admissible&&comparable"

# A boolean AND that combines an admissibility truth check with a comparability
# truth check is the signature of a duplicated D6 rule; only the canonical
# derivation may contain one (comments already stripped).
D6_COMBINATION_RE = re.compile(
    r"admissible[^\n;]{0,80}&&[^\n;]{0,80}comparable"
    r"|comparable[^\n;]{0,80}&&[^\n;]{0,80}admissible"
)


def _detected_exposure_paths() -> set[str]:
    """Functions that touch the preflop payload and therefore need a gate.

    Two complementary detectors so a new path is caught whether it reads the raw
    ``poker-preflop-decision/v1`` fields or the derived Trainer fields:

    * derived detector: a function that mentions ``preflopDecision`` and any raw
      or derived Hero field;
    * raw detector: a function that reads a raw preflop EV field *and* uses the
      canonical view (covers the summary, which receives the decision directly
      rather than through a ``preflopDecision`` property).
    """
    derived = {
        name
        for name, body in BODIES.items()
        if "preflopDecision" in body
        and any(field in body for field in RAW_PREFLOP_EV_FIELDS + RAW_PREFLOP_ACTION_FIELDS + DERIVED_HERO_FIELDS)
    }
    raw = {
        name
        for name, body in BODIES.items()
        if any(field in body for field in RAW_PREFLOP_EV_FIELDS)
        and "trainerPreflopDecisionView" in body
    }
    return derived | raw


class TrainerD6ExposureContract(unittest.TestCase):
    # ----------------------------------------------------- canonical derivation
    def test_show_ev_rule_lives_once_in_the_canonical_derivation(self):
        self.assertIn(DERIVATION_FUNCTION, BODIES, "missing the canonical derivation")
        self.assertEqual(
            CODE.count(D6_RULE_LITERAL),
            1,
            "the D6 rule must be declared exactly once",
        )
        self.assertIn(D6_RULE_LITERAL, BODIES[DERIVATION_FUNCTION])
        combinators = [
            name for name, body in BODIES.items() if D6_COMBINATION_RE.search(body)
        ]
        self.assertEqual(
            combinators,
            [DERIVATION_FUNCTION],
            f"only {DERIVATION_FUNCTION} may combine admissible && comparable",
        )

    def test_the_two_source_dimensions_are_only_read_by_view_and_technical_panel(self):
        readers = sorted(
            name
            for name, body in BODIES.items()
            if "recommendation_admissibility" in body and "ev_comparability" in body
        )
        self.assertEqual(readers, sorted([DERIVATION_FUNCTION, TECHNICAL_PANEL_FUNCTION]))

    def test_derivation_delegates_to_the_shared_module(self):
        # The shared module is the source of truth and must be loaded before the
        # Trainer in the served page.
        module_tag = '<script src="./analytics/analysis-state.js"></script>'
        self.assertTrue(module_tag in INDEX, "shared analysis-state module must be loaded")
        self.assertLess(
            INDEX.index(module_tag),
            INDEX.index('<script src="./trainer.js"></script>'),
            "analysis-state must load before trainer.js",
        )
        self.assertIn("trainerPreflopAnalysis(decision)", BODIES[DERIVATION_FUNCTION])
        self.assertTrue(
            "Module.mapAnalysisState(decision)" in CODE,
            "the derivation must feed the preflop decision to the shared mapper untouched",
        )
        self.assertTrue(
            "window.PokerAnalysisState" in CODE,
            "the shared analysis-state runtime must be loaded by the Trainer",
        )
        # The technical panel is only reached from the secondary feedback summary.
        summary = BODIES["trainerPreflopDecisionSummaryHtml"]
        self.assertIn("trainerAnalysisDimensionsHtml(view.analysis)", summary)
        # Rule D6 shape: admissible/comparable read from the two dimensions.
        view = BODIES[DERIVATION_FUNCTION]
        self.assertIn("recommendation_admissibility?.admissible===true", view)
        self.assertIn("ev_comparability?.comparable===true", view)

    # ----------------------------------------------------- per-path D6 gating
    def test_every_registered_path_exists_and_uses_its_canonical_gate(self):
        for name, spec in D6_EXPOSURE_REGISTRY.items():
            with self.subTest(path=name):
                self.assertIn(name, BODIES, f"registered exposure path disappeared: {name}")
                body = BODIES[name]
                kind = spec["kind"]
                if kind == "show_ev":
                    self.assertTrue(
                        "show_ev" in body,
                        f"{name} must gate its recommendation/EV exposure on `view.show_ev`",
                    )
                elif kind == "admissible":
                    self.assertTrue("trainerPreflopDecisionView" in body, name)
                    self.assertTrue(".admissible" in body, name)
                    # The admissibility half-gate may only expose the action kind,
                    # never an EV field.
                    for field in RAW_PREFLOP_EV_FIELDS:
                        self.assertFalse(
                            field in body,
                            f"{name} may not expose {field} behind the admissibility half-gate",
                        )
                elif kind == "compute":
                    self.assertTrue("trainerDetailFromPreflopDecision(" in body, name)
                    for forbidden in (
                        "show_ev",
                        D6_RULE_LITERAL,
                        "recommendation_admissibility",
                        "ev_comparability",
                    ):
                        self.assertFalse(
                            forbidden in body,
                            f"{name} must delegate D6 rather than recombine it ({forbidden})",
                        )
                else:  # pragma: no cover - registry typo guard
                    self.fail(f"unknown gate kind {kind!r} for {name}")

    def test_canonical_view_is_derived_before_any_raw_preflop_field(self):
        for name, spec in D6_EXPOSURE_REGISTRY.items():
            if spec["kind"] != "show_ev":
                continue
            fields = [f for f in spec["raw_fields"] if f in BODIES[name]]
            if not fields:
                continue
            with self.subTest(path=name):
                body = BODIES[name]
                self.assertTrue(
                    "trainerPreflopDecisionView" in body,
                    f"{name} must derive the canonical view before exposing D6 fields",
                )
                first_raw = min(body.index(field) for field in fields)
                self.assertLess(
                    body.index("trainerPreflopDecisionView"),
                    first_raw,
                    f"{name} must derive the canonical view before touching {fields}",
                )

    def test_no_unregistered_preflop_exposure_path(self):
        detected = _detected_exposure_paths()
        unregistered = detected - set(D6_EXPOSURE_REGISTRY)
        self.assertEqual(
            unregistered,
            set(),
            f"unregistered Hero preflop exposure path(s): {sorted(unregistered)}",
        )
        # Symmetry: every registry entry must still be an actual exposure path,
        # so a stale entry cannot mask a renamed/removed gate.
        self.assertEqual(
            detected,
            set(D6_EXPOSURE_REGISTRY),
            "the registry and the detected preflop exposure paths must stay in sync",
        )

    # --------------------------------------------------- no legacy gate remains
    def test_no_legacy_covered_only_gate_remains_in_the_trainer(self):
        self.assertFalse(
            "isCovered" in CODE,
            "PokerPreflopRuntime.isCovered must never gate a Training Hero exposure",
        )
        # The generic module may still be used to *build* runtime inputs; it must
        # not be used to decide whether a recommendation/EV is shown.
        for token in (
            'coverage_state==="COVERED"',
            "coverage_state === 'COVERED'",
            "covered&&",
        ):
            self.assertFalse(
                token in CODE,
                f"legacy covered-only gate reintroduced: {token}",
            )

    # ----------------------------------------------------------- byte parity
    def test_source_and_site_analysis_state_are_byte_identical(self):
        self.assertTrue(SOURCE.is_file(), "missing src/analytics/analysis-state.js")
        self.assertTrue(MIRROR.is_file(), "missing site/analytics/analysis-state.js")
        source = SOURCE.read_bytes()
        mirror = MIRROR.read_bytes()
        if source == mirror:
            return
        shared = min(len(source), len(mirror))
        offset = next(
            (i for i in range(shared) if source[i] != mirror[i]),
            shared,
        )
        line = source[:offset].count(b"\n") + 1
        self.fail(
            "src/analytics/analysis-state.js and site/analytics/analysis-state.js "
            f"diverge at line {line} (offset {offset}); source {len(source)} bytes, "
            f"mirror {len(mirror)} bytes"
        )

    def test_parity_and_exposure_guards_are_wired_into_ci(self):
        # The dedicated analysis-state workflow keeps running the byte-parity
        # guard and triggers on both mirror paths.
        self.assertTrue(
            "node tests/analytics/test_analysis_state_mirror_parity.js" in ANALYSIS_WORKFLOW,
            "the dedicated workflow must keep executing the byte-parity guard",
        )
        for path in ("src/analytics/analysis-state.js", "site/analytics/analysis-state.js"):
            self.assertTrue(path in ANALYSIS_WORKFLOW, f"CI must trigger on {path}")
        # This contract itself runs in the frozen trainer smoke job, which iterates
        # every tests/trainer/test_*.py and triggers on tests/trainer/**.
        self.assertTrue(
            "for test in tests/trainer/test_*.py; do" in TRAINER_WORKFLOW,
            "the trainer smoke job must keep running every tests/trainer contract",
        )
        self.assertEqual(TRAINER_WORKFLOW.count("'tests/trainer/**'"), 2)
        self.assertTrue(
            Path(__file__).name in ANALYSIS_WORKFLOW,
            "the dedicated analysis-state workflow must execute this exposure guard",
        )

    # --------------------------------------------- taxonomy semantics intact
    def test_canonical_taxonomy_semantics_are_unchanged(self):
        self.assertEqual(SCHEMA["properties"]["state"]["enum"], CANONICAL_STATES)
        self.assertEqual(len(set(CANONICAL_STATES)), 6)
        self.assertIn(
            "NOT_EVALUATED", SCHEMA["properties"]["computational_status"]["enum"]
        )
        support = SCHEMA["properties"]["statistical_support"]["properties"]
        for field in ("observations", "distinct_hands"):
            self.assertEqual(support[field]["type"], "integer")
        # The D5 (adverse surfaces) and D6 (Hero EV) rules stay documented.
        for needle in ("## Règle D5", "## Règle D6", "admissible === true", "comparable === true"):
            self.assertTrue(needle in DOC, f"canonical contract rule disappeared: {needle}")

    # ------------------------------- runtime proof for non-static-only paths
    def test_runtime_sanitization_backs_the_non_local_controls_path(self):
        """``trainerRenderControls`` reads ``recommendation.bestCostBB`` directly.

        No local D6 gate exists there, so a static assertion is impossible. The
        guarantee is that the detail produced by the canonical derivation carries
        ``bestCostBB === null`` (and NaN EVs) when D6 is closed even though the raw
        decision still carries a sizing. This is the runtime behaviour the T4 D6
        render matrix (``test_d6_render_matrix_contract.py`` +
        ``smoke_trainer_d6_render_matrix.py``) exercises end-to-end.
        """
        self.assertTrue(D6_CONTRACT.is_file(), "missing T4 D6 matrix contract")
        self.assertTrue(D6_DRIVER.is_file(), "missing T4 D6 matrix driver")
        fixture = json.loads(D6_FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(fixture["schema"], "trainer-d6-render-matrix/v1")
        self.assertEqual([c["name"][0] for c in fixture["cases"]], ["A", "B", "C", "D", "E"])

        if NODE is None:  # pragma: no cover - CI installs node
            self.skipTest("node is required for the Trainer D6 runtime proof")
        script = r"""
const fs=require('fs');
const src=fs.readFileSync('site/trainer.js','utf8');
const start=src.indexOf('function trainerAnalysisModule(');
const end=src.indexOf('function trainerDecisionClass(');
if(start<0||end<0)throw new Error('trainer analysis helpers missing');
const helpers=src.slice(start,end);
const State=require('./src/analytics/analysis-state.js');
const LABELS={
  ANALYSE_DISPONIBLE:'Analyse disponible',ANALYSE_PARTIELLE:'Analyse partielle',
  CALCUL_EN_COURS:'Calcul en cours',DONNEES_INSUFFISANTES:'Données insuffisantes',
  SPOT_NON_SUPPORTE:'Spot non supporté',ERREUR_CALCUL:'Erreur de calcul'
};
const window={PokerAnalysisState:State,PokerReviewInbox:{analysisStateLabel:s=>LABELS[String(s||'').toUpperCase()]||'Analyse indisponible'}};
const factory=new Function('window',helpers+'\nreturn {trainerPreflopDecisionView,trainerDetailFromPreflopDecision};');
const api=factory(window);
function probe(decision){
  const view=api.trainerPreflopDecisionView(decision);
  const detail=api.trainerDetailFromPreflopDecision(decision,null);
  return {show_ev:view.show_ev,bestCostBB:detail.bestCostBB,bestEV:Number.isFinite(detail.bestEV)?detail.bestEV:null,
    chosenEV:Number.isFinite(detail.chosenEV)?detail.chosenEV:null,raw_cost:decision.incremental_cost_bb};
}
const closed=probe({coverage_state:'COVERED',recommended_action:'3BET',recommended_ev_bb:1.6,played_ev_bb:0.2,
  incremental_cost_bb:8,ev_comparable:false,reason_codes:['NON_COMPARABLE_ALTERNATIVES'],
  recommendation_admissibility:{admissible:true,status:'ADMISSIBLE',reason_codes:[]}});
const open=probe({coverage_state:'COVERED',recommended_action:'CALL',recommended_ev_bb:0.42,played_ev_bb:0.3,
  incremental_cost_bb:2.5,ev_comparable:true,reason_codes:[],
  recommendation_admissibility:{admissible:true,status:'ADMISSIBLE',reason_codes:[]}});
if(closed.show_ev!==false)throw new Error('closed fixture must fail closed');
if(closed.raw_cost!==8)throw new Error('closed fixture must carry a raw sizing (else the proof is vacuous)');
if(closed.bestCostBB!==null)throw new Error('closed detail leaked a recommendation sizing');
if(closed.bestEV!==null||closed.chosenEV!==null)throw new Error('closed detail leaked a Hero EV');
if(open.show_ev!==true)throw new Error('open fixture must expose the recommendation');
if(open.bestCostBB!==2.5||open.bestEV!==0.42)throw new Error('open fixture must preserve the Hero fields');
console.log(JSON.stringify({status:'PASS',closed,open}));
"""
        proc = subprocess.run(
            [NODE, "-e", script],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(proc.stdout.strip().splitlines()[-1])
        self.assertEqual(payload["status"], "PASS")
        self.assertFalse(payload["closed"]["show_ev"])
        self.assertIsNone(payload["closed"]["bestCostBB"])
        self.assertIsNone(payload["closed"]["bestEV"])
        self.assertIsNone(payload["closed"]["chosenEV"])
        self.assertEqual(payload["closed"]["raw_cost"], 8)
        self.assertTrue(payload["open"]["show_ev"])
        self.assertEqual(payload["open"]["bestCostBB"], 2.5)
        self.assertEqual(payload["open"]["bestEV"], 0.42)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
import hashlib, json, re, shutil, subprocess, sys, tempfile, unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools import audit_github_workflows as audit
from tools import audit_active_workflow_dag as dag

# Issue #419 ships one authoritative workflow. It must actually execute every
# #419 suite (not merely declare them in its `paths` filters) and its path
# filters must cover every file the issue changes. Both properties are guarded
# here, together with negative tests proving the guards are not vacuous: an
# execution-only declaration, a dropped trigger pattern (drift) and a swapped
# trigger pattern (substitution) must each be detected.
ISSUE_419_WORKFLOW=".github/workflows/issue-419-hierarchical-exact-tree.yml"
ISSUE_419_EVENTS=("push","pull_request")
ISSUE_419_SUITES=(
    "tests/simulation/test_issue419_exact_tree_preflight.py",
    "tests/preflop/test_model_a_sizing_hierarchical.py",
    "tests/training/test_hierarchical_train_fit.py",
    "tests/training/test_hierarchical_validation_evaluation.py",
    "tests/training/test_hierarchical_terminal_decision.py",
    "tests/training/test_hierarchical_model_spec.py",
    "tests/training/test_hierarchical_candidate_contract.py",
    "tests/training/test_hierarchical_exact_context_contract_doc.py",
    "tests/training/test_hierarchical_tree_sparsity_parity.py",
    "tests/training/test_frozen_validation_protocol.py",
    "tests/training/test_frozen_validation_protocol_v2.py",
    "tests/training/test_raise_sizing_frontier_resolution.py",
)
ISSUE_419_EXTRA_SUITES=(
    "tests/training/test_issue419_hierarchical_exact_tree.py",
    "tests/test_github_workflow_audit.py",
)
# The #419 change surface: every path the issue actually ships must trigger the
# authoritative runner.  `test_issue419_trigger_paths_cover_the_issue_surface`
# cross-checks this manifest against the real branch diff when git history is
# available, so the list can never silently rot.
ISSUE_419_CHANGED_PATHS=(
    # production tools and the shared hierarchical provider
    "tools/preflop/model_a_sizing_hierarchical.py",
    "tools/simulation/issue419_exact_tree_preflight.py",
    "tools/training/fit_model_a_preflop_sizing_hierarchical.py",
    "tools/training/finalize_hierarchical_exact_tree_decision.py",
    "tools/training/resolve_raise_sizing_frontiers.py",
    "tools/training/write_frozen_validation_protocol.py",
    "tools/training/write_frozen_validation_protocol_v2.py",
    "tools/training/write_hierarchical_model_spec.py",
    "tools/training/validate_hierarchical_validation.py",
    "tools/training/validation_order_guard.py",
    "tools/training/audit_hierarchical_candidate_contract.py",
    "tools/training/audit_hierarchical_tree_sparsity.py",
    "tools/audit_active_workflow_dag.py",
    # candidate contract (the #419 contract and its #388 sibling)
    "contracts/training/model-a-preflop-sizing-hierarchical-likelihood.schema.json",
    "contracts/training/model-a-preflop-sizing-likelihood.schema.json",
    # documentation
    "docs/hierarchical-exact-context-model.md",
    "docs/hierarchical-exact-context-runtime-contract.md",
    "docs/hierarchical-exact-context-validation-protocol.md",
    "docs/model-a-posterior-runtime.md",
    "docs/reviewer-preflop-iso-analysis.md",
    # decision records
    ".project/decisions/20260925-exact-tree-367-preflight.md",
    ".project/decisions/20260925-hierarchical-candidate-contract.md",
    ".project/decisions/20260925-hierarchical-exact-context-model-spec.md",
    ".project/decisions/20260925-hierarchical-exact-context-runtime-contract.md",
    ".project/decisions/20260925-hierarchical-exact-tree-terminal-decision.md",
    ".project/decisions/20260925-hierarchical-validation-evaluation.md",
    ".project/decisions/20260925-hierarchical-validation-protocol.md",
    ".project/decisions/20260926-hierarchical-validation-protocol-v2.md",
    # content-addressed #419 evidence (the directory glob must cover all of it)
    "analysis/issue419_hierarchical_tree/SUMMARY.md",
    "analysis/issue419_hierarchical_tree/HIERARCHICAL_MODEL_SPEC.json",
    "analysis/issue419_hierarchical_tree/FROZEN_VALIDATION_PROTOCOL.json",
    "analysis/issue419_hierarchical_tree/validation_protocol_v2/FROZEN_VALIDATION_PROTOCOL_V2.json",
    "analysis/issue419_hierarchical_tree/fit/CANDIDATE.json",
    "analysis/issue419_hierarchical_tree/terminal_decision/DECISION.json",
    "analysis/issue419_hierarchical_tree/validation/VALIDATION_RESULT.json",
    "analysis/issue419_hierarchical_tree/exact_tree_preflight/EXACT_TREE_PREFLIGHT.json",
    "analysis/issue419_hierarchical_tree/exact_tree_preflight_v2/EXACT_TREE_PREFLIGHT_V2.json",
    "analysis/issue419_hierarchical_tree/raise_sizing_frontiers/RAISE_SIZING_FRONTIER_RESOLUTION.json",
    # the suites this workflow is authoritative for (including the audit guard itself)
    *ISSUE_419_SUITES,
    *ISSUE_419_EXTRA_SUITES,
    "tests/ci/test_consolidation_decision.py",
    # the workflow and its regenerated audit evidence
    ISSUE_419_WORKFLOW,
    "analysis/workflow_audit/workflows.json",
    "analysis/workflow_audit/active_workflow_dag_v2.json",
    "analysis/workflow_audit/consolidation_decision_v1.json",
    "docs/ci-workflow-dag.md",
)

# Inputs the runner consumes or executes but the issue does not itself change: an
# edit to any of them must still re-run the authoritative surface, so they are
# trigger-required even though they are not part of the #419 diff.
ISSUE_419_EXTERNAL_DEPENDENCIES=(
    "tools/audit_github_workflows.py",
    "analysis/issue388_exact_tree/REQUIRED_EXACT_TREE.json",
)
ISSUE_419_TRIGGER_REQUIRED_PATHS=*ISSUE_419_CHANGED_PATHS,*ISSUE_419_EXTERNAL_DEPENDENCIES


def issue419_executed_suites(text: str) -> set[str]:
    """Suites the workflow really runs: a `python3 <suite>` command outside a comment."""
    executable="\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    return {suite for suite in ISSUE_419_SUITES
            if re.search(r"python3\s+"+re.escape(suite)+r"(?:\s|$)",executable)}


def issue419_uncovered_paths(text: str, paths=ISSUE_419_TRIGGER_REQUIRED_PATHS) -> list[tuple[str, str]]:
    """(event, path) pairs a #419 change would land on *without* triggering the runner."""
    triggers=audit.parse_triggers(text.splitlines())
    uncovered=[]
    for event in ISSUE_419_EVENTS:
        patterns=triggers.get(event,{}).get("paths",[])
        for path in paths:
            if not any(dag._glob(pattern,path) for pattern in patterns):
                uncovered.append((event,path))
    return uncovered


def issue419_changed_paths() -> list[str] | None:
    """The real #419 change surface, or None when git history is unavailable (shallow checkout)."""
    try:
        base=subprocess.check_output(["git","merge-base","origin/main","HEAD"],cwd=ROOT,text=True,
                                     stderr=subprocess.DEVNULL).strip()
        diff=subprocess.check_output(["git","diff","--name-only",f"{base}..HEAD"],cwd=ROOT,text=True,
                                     stderr=subprocess.DEVNULL).split()
    except (subprocess.CalledProcessError,FileNotFoundError):
        return None
    return sorted(path for path in diff if (ROOT/path).exists())

HISTORICAL_EVIDENCE=(
    "analysis/workflow_audit/historical_workflow_quarantine_v1.json",
    "analysis/workflow_audit/repro_composite_factorization_v1.json",
    "analysis/workflow_audit/repro_batch1_before_after.json",
    "analysis/workflow_audit/repro_batch2_before_after.json",
    "analysis/workflow_audit/repro_population_pack_catalog_before_after.json",
    "analysis/workflow_audit/repro_current_mixed_batch_before_after.json",
    "analysis/workflow_audit/repro_current_core_batch_before_after.json",
    "analysis/workflow_audit/residual_repro_dag_before_after.json",
    "analysis/workflow_audit/baseline_metrics.json",
)

SAMPLE="""name: Sample browser workflow
on:
  push:
    branches:
      - main
    paths:
      - 'site/**'
      - tests/browser/**
  pull_request:
    paths:
      - site/**
concurrency:
  group: sample-${{ github.ref }}
  cancel-in-progress: true
jobs:
  contract:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
      - run: python tests/test_contract.py
  smoke:
    needs: contract
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: python3 -m pip install playwright
      - run: python3 -m playwright install --with-deps chromium
      - uses: actions/upload-artifact@v4
        with:
          name: smoke-output
          path: /tmp/out
"""
class WorkflowAuditTests(unittest.TestCase):
    def test_parse_paths_jobs_concurrency_and_cost(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); p=root/".github/workflows/sample.yml"; p.parent.mkdir(parents=True); p.write_text(SAMPLE)
            r=audit.parse_workflow(p,root)
            self.assertEqual(["site/**","tests/browser/**"],r["triggers"]["push"]["paths"])
            self.assertEqual(["site/**"],r["triggers"]["pull_request"]["paths"])
            self.assertIs(r["concurrency"]["cancel_in_progress"],True)
            self.assertEqual(["contract"],r["jobs"][1]["needs"])
            self.assertEqual(["smoke-output"],r["artifacts"]["uploads"])
            self.assertEqual(2,r["duplication_primitives"]["checkout"])
            self.assertEqual(1,r["duplication_primitives"]["playwright_install"])
            self.assertEqual("medium",r["cost_proxy"]["band"])
    def test_workflow_run_dependency_is_explicit_edge(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); d=root/".github/workflows"; d.mkdir(parents=True)
            (d/"source.yml").write_text("name: Source\non: workflow_dispatch\njobs:\n  a:\n    runs-on: ubuntu-latest\n")
            (d/"sink.yml").write_text("""name: Sink
on:
  workflow_run:
    workflows:
      - Source
    types:
      - completed
jobs:
  b:
    runs-on: ubuntu-latest
""")
            r=audit.audit_repository(root)
            self.assertEqual(2,r["workflow_count"])
            self.assertEqual("Source",r["aggregate"]["workflow_run_edges"][0]["from_name"])
            self.assertTrue(r["aggregate"]["workflow_run_edges"][0]["from_path"].endswith("source.yml"))
    def test_lifecycle_classification(self):
        self.assertEqual("historical_candidate","historical_candidate" if "preflop-strategy-validation-v2.yml" in audit.HISTORICAL_CANDIDATES else "")
        self.assertEqual("frozen_current","frozen_current" if "preflop-strategy-validation-pfpc.yml" in audit.FROZEN_CURRENT else "")

    def test_inventory_covers_every_workflow_at_head(self):
        data=audit.inventory(ROOT)
        files={p.relative_to(ROOT).as_posix() for p in audit.workflow_paths(ROOT)}
        self.assertEqual(audit.INVENTORY_SCHEMA,data["schema"])
        self.assertEqual(audit.SNAPSHOT_BASE_SHA,data["snapshot_base_sha"])
        self.assertEqual(len(files),data["workflow_count"])
        self.assertEqual(files,{row["path"] for row in data["workflows"]})
        for row in data["workflows"]:
            for key in ("role","triggers","jobs","concurrency","artifacts","cost_proxy"):
                self.assertIn(key,row,row["path"])
            self.assertEqual(row["automatic"],audit.automatic(dict.fromkeys(row["triggers"])))
        automatic=[row for row in data["workflows"] if row["automatic"]]
        manual=[row for row in data["workflows"] if not row["automatic"]]
        self.assertEqual(len(automatic),data["aggregate"]["automatic_trigger_workflows"])
        self.assertEqual(len(manual),data["aggregate"]["manual_only_workflows"])
        self.assertEqual({row["path"] for row in manual},set(data["aggregate"]["historical_candidates"]))
        for row in manual:
            self.assertEqual(["workflow_dispatch"],row["triggers"])

    def test_historical_evidence_sha256_is_invariant(self):
        recorded={path:hashlib.sha256((ROOT/path).read_bytes()).hexdigest() for path in HISTORICAL_EVIDENCE}
        self.assertEqual(audit.HISTORICAL_EVIDENCE_SHA256,recorded)
        self.assertEqual(audit.HISTORICAL_EVIDENCE_SHA256,audit.verify_historical_evidence(ROOT))
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for path in HISTORICAL_EVIDENCE:
                target=root/path; target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(ROOT/path,target)
            (root/HISTORICAL_EVIDENCE[0]).write_text("{}\n")
            with self.assertRaises(ValueError):
                audit.verify_historical_evidence(root)

    def test_committed_inventory_is_regenerable(self):
        committed=json.loads((ROOT/"analysis/workflow_audit/workflows.json").read_text())
        regenerated=audit.inventory(ROOT)
        self.assertEqual(committed,regenerated)

    def test_issue419_changed_paths_are_all_covered_by_the_workflow(self):
        """Every #419 change must trigger the authoritative workflow on push and on pull_request."""
        text=(ROOT/ISSUE_419_WORKFLOW).read_text()
        triggers=audit.parse_triggers(text.splitlines())
        self.assertIn("push",triggers,ISSUE_419_WORKFLOW)
        self.assertIn("pull_request",triggers,ISSUE_419_WORKFLOW)
        for changed in ISSUE_419_TRIGGER_REQUIRED_PATHS:
            self.assertTrue((ROOT/changed).exists(),f"declared #419 path is missing: {changed}")
        self.assertEqual([],issue419_uncovered_paths(text))

    def test_issue419_trigger_paths_cover_the_issue_surface(self):
        """Completeness: the filters must cover the real branch diff, not only a curated list."""
        changed=issue419_changed_paths()
        if changed is None:
            self.skipTest("git history unavailable (shallow checkout): set fetch-depth: 0 to enforce this")
        if not changed:
            # The checkout tip is its own merge-base with origin/main (post-merge push):
            # there is no changed surface to cross-check here.
            self.skipTest("branch tip equals its merge-base with origin/main: nothing to cross-check")
        text=(ROOT/ISSUE_419_WORKFLOW).read_text()
        self.assertEqual([],issue419_uncovered_paths(text,changed),
                         "the #419 change surface exposes paths the runner never triggers on")
        # The curated manifest must stay a subset of the real surface, so it can never
        # assert coverage for a path the issue does not actually ship.
        fabricated=set(ISSUE_419_CHANGED_PATHS)-set(changed)
        self.assertEqual(set(),fabricated,f"manifest claims paths outside the #419 diff: {sorted(fabricated)}")

    def test_issue419_trigger_drift_and_substitution_are_detected(self):
        """Negative guard: dropping or swapping a trigger pattern must be detected."""
        text=(ROOT/ISSUE_419_WORKFLOW).read_text()
        # (a) drift: the pre-hardening filters did not cover the audit chain.
        drifted=text.replace("      - 'tests/**'\n","      - 'tests/training/test_hierarchical_*.py'\n")
        uncovered={path for _,path in issue419_uncovered_paths(drifted)}
        self.assertIn("tests/ci/test_consolidation_decision.py",uncovered)
        self.assertIn("tests/simulation/test_issue419_exact_tree_preflight.py",uncovered)
        # (b) substitution: a nearby path that looks right but is not the shipped one.
        substituted=text.replace("      - 'tests/**'\n","      - 'tests/preflop/**'\n")
        self.assertIn(("push","tests/training/test_hierarchical_train_fit.py"),
                      issue419_uncovered_paths(substituted))
        # (c) a silently-renamed evidence directory must also be flagged.
        renamed=text.replace("'analysis/issue419_hierarchical_tree/**'","'analysis/issue419_hierarchical_trees/**'")
        self.assertIn(("pull_request","analysis/issue419_hierarchical_tree/fit/CANDIDATE.json"),
                      issue419_uncovered_paths(renamed))

    def test_issue419_workflow_executes_every_suite(self):
        """The workflow must run each of the 12 #419 suites as a real command, not a declaration."""
        text=(ROOT/ISSUE_419_WORKFLOW).read_text()
        self.assertEqual(set(ISSUE_419_SUITES)-issue419_executed_suites(text),set())
        # Each suite is executed independently so a failure cannot be masked by a later step.
        for suite in ISSUE_419_SUITES:
            with self.subTest(suite=suite):
                self.assertRegex(text,r"python3\s+"+re.escape(suite)+r"(?:\s|$)")

    def test_issue419_noop_workflow_is_detected(self):
        """Negative guard: a workflow that only declares the suites in `paths` must be flagged."""
        text=(ROOT/ISSUE_419_WORKFLOW).read_text()
        declaration_only="\n".join(
            line for line in text.splitlines()
            if line.lstrip().startswith(("-","'")) or line.startswith("on:") or line.startswith("  paths:"))
        self.assertEqual(set(),issue419_executed_suites(declaration_only))
        # Dropping a single executed command is also detected, so the guard cannot silently pass.
        for suite in ISSUE_419_SUITES:
            with self.subTest(suite=suite):
                dropped="\n".join(line for line in text.splitlines() if suite not in line)
                self.assertIn(suite,set(ISSUE_419_SUITES)-issue419_executed_suites(dropped))

    def test_issue419_workflow_is_read_only_and_registered(self):
        """The #419 runner publishes no artifact and never widens the write surface."""
        text=(ROOT/ISSUE_419_WORKFLOW).read_text()
        self.assertIn("permissions:\n  contents: read",text)
        for forbidden in ("upload-artifact","git push","pull_request_target","gh release create","wrangler deploy"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden,text)
        row=next(r for r in audit.inventory(ROOT)["workflows"] if r["path"]==ISSUE_419_WORKFLOW)
        self.assertTrue(row["automatic"])
        self.assertEqual(row["triggers"],["push","pull_request","workflow_dispatch"])
        self.assertEqual(row["artifacts"],[])

    def test_issue419_decision_artifact_classifies_the_workflow_as_safe(self):
        decision=json.loads((ROOT/dag.DECISION).read_text())
        row=next(r for r in decision["workflows"] if r["path"]==ISSUE_419_WORKFLOW)
        self.assertEqual("READ_ONLY",row["side_effect_class"])
        self.assertIs(row["fail_closed_safe"],True)
        self.assertEqual("SAFE_CANDIDATE_NOT_APPLIED",row["recommendation_state"])
        self.assertTrue(row["blockers"])
if __name__=="__main__": unittest.main()

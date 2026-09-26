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
# Suites the branch ships outside the #419 test surface that the authoritative
# runner must also execute: the #204 consolidation-decision mutation guard (the
# decision artifact's own fail-closed tests). It is executed by no other workflow,
# so an unexecuted regression here would otherwise stay implicit.
ISSUE_419_CI_SUITES=(
    "tests/ci/test_consolidation_decision.py",
)
# Every suite the runner must run as a real step: `ISSUE_419_SUITES ∪ ISSUE_419_EXTRA_SUITES`
# (the union the workflow's no-op guard mirrors) plus the shared audit chain above.
ISSUE_419_REQUIRED_SUITES=ISSUE_419_SUITES+ISSUE_419_EXTRA_SUITES+ISSUE_419_CI_SUITES
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
    *ISSUE_419_CI_SUITES,
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
    return executed_suites(text,ISSUE_419_REQUIRED_SUITES)


def issue419_declared_required_suites(text: str) -> set[str]:
    """The suites the workflow's own `required = (...)` no-op guard asserts it executed."""
    return declared_required_suites(text)


def issue419_uncovered_paths(text: str, paths=ISSUE_419_TRIGGER_REQUIRED_PATHS) -> list[tuple[str, str]]:
    """(event, path) pairs a #419 change would land on *without* triggering the runner."""
    return uncovered_paths(text,paths,ISSUE_419_EVENTS)


def issue419_changed_paths() -> list[str] | None:
    """The real #419 change surface, or None when git history is unavailable (shallow checkout)."""
    return issue_changed_paths(419)


# ---------------------------------------------------------------------------
# Issue #421 ships one authoritative workflow with the same two properties: it
# must execute every #421 suite and its path filters must cover every file the
# issue changes.  The constants below are the machine-readable projection of
# the ticket (T1..T11 plus the T12 evidence bundle) mirrored by the workflow's
# own `required = (...)` no-op guard.
# ---------------------------------------------------------------------------
ISSUE_421_WORKFLOW=".github/workflows/issue-421-generalized-response-model.yml"
ISSUE_421_EVENTS=("push","pull_request")
ISSUE_421_SUITES=(
    "tests/training/test_build_generalized_response_dataset.py",
    "tests/training/test_audit_generalized_response_features.py",
    "tests/preflop/test_generalized_response_model.py",
    "tests/training/test_evaluate_generalized_response_cv.py",
    "tests/preflop/test_generalized_response_sizing.py",
    "tests/preflop/test_generalized_response_ood.py",
    "tests/training/test_frozen_generalized_validation_protocol.py",
    "tests/training/test_validate_generalized_response.py",
    "tests/preflop/test_generalized_response_runtime.py",
    "tests/simulation/test_issue421_preflight.py",
    "tests/preflop/test_issue421_mandatory_contracts.py",
    "tests/ci/test_issue421_contract_guards.py",
    "tests/training/test_issue421_evidence_bundle.py",
)
# Suite #421 ships outside the T1..T11 model surface that the authoritative
# runner must also execute: this audit guard itself, which asserts the runner's
# trigger/execution/read-only contract.
ISSUE_421_EXTRA_SUITES=(
    "tests/test_github_workflow_audit.py",
)
# The shared #204 consolidation-decision mutation guard the runner re-proves at
# the end of the job: it is not part of the #421 diff, but the runner executes
# it and must therefore trigger on it (see ISSUE_421_EXTERNAL_DEPENDENCIES).
ISSUE_421_CI_SUITES=(
    "tests/ci/test_consolidation_decision.py",
)
ISSUE_421_REQUIRED_SUITES=ISSUE_421_SUITES+ISSUE_421_EXTRA_SUITES+ISSUE_421_CI_SUITES
# The #421 change surface: every path the issue ships must trigger the
# authoritative runner.  `test_issue421_trigger_paths_cover_the_issue_surface`
# cross-checks the manifest against the real branch diff -- the *whole* diff
# restricted to the #421-stamped commits -- when git history is available, so
# the list can never silently rot; the content-addressed `sha256/` copies are
# enumerated by that diff rather than repeated here.
ISSUE_421_CHANGED_PATHS=(
    # production tools: the frozen model, the runtime provider, the preflight
    # and every tools/training generator the ticket ships
    "tools/preflop/generalized_response_model.py",
    "tools/preflop/generalized_response_runtime.py",
    "tools/simulation/issue421_issue367_preflight.py",
    "tools/training/audit_generalized_response_features.py",
    "tools/training/build_generalized_response_dataset.py",
    "tools/training/build_issue421_evidence_bundle.py",
    "tools/training/evaluate_generalized_response_cv.py",
    "tools/training/freeze_generalized_validation_protocol.py",
    "tools/training/validate_generalized_response.py",
    # contracts
    "contracts/training/generalized-response-dataset.schema.json",
    "contracts/training/generalized-response-model.schema.json",
    "contracts/training/generalized-response-ood-gate.schema.json",
    "contracts/training/generalized-validation-protocol.schema.json",
    # the suites this workflow is authoritative for (including the audit guard)
    *ISSUE_421_SUITES,
    *ISSUE_421_EXTRA_SUITES,
    # documentation and decision records
    "docs/generalized-opponent-response-model.md",
    ".project/decisions/20260926-generalized-opponent-response-model.md",
    # content-addressed evidence (the `analysis/issue421_generalized_response/**`
    # trigger must cover the whole tree; these are the anchor artifacts and the
    # ones the index binds)
    "analysis/issue421_generalized_response/ARTIFACTS.json",
    "analysis/issue421_generalized_response/CANDIDATE_MANIFEST.json",
    "analysis/issue421_generalized_response/CANDIDATE_MANIFEST.sha256",
    "analysis/issue421_generalized_response/DECISION.json",
    "analysis/issue421_generalized_response/DECISION.sha256",
    "analysis/issue421_generalized_response/FROZEN_VALIDATION_PROTOCOL.json",
    "analysis/issue421_generalized_response/FROZEN_VALIDATION_PROTOCOL.sha256",
    "analysis/issue421_generalized_response/GENERALIZED_RESPONSE_DATASET_REPORT.json",
    "analysis/issue421_generalized_response/GENERALIZED_RESPONSE_MODEL_SPEC.json",
    "analysis/issue421_generalized_response/GENERALIZED_RESPONSE_MODEL_SPEC.sha256",
    "analysis/issue421_generalized_response/ISSUE367_PREFLIGHT.json",
    "analysis/issue421_generalized_response/ISSUE367_PREFLIGHT.sha256",
    "analysis/issue421_generalized_response/OOD_CALIBRATION_REPORT.json",
    "analysis/issue421_generalized_response/RAISE_SIZING_MODEL_REPORT.json",
    "analysis/issue421_generalized_response/SUMMARY.md",
    "analysis/issue421_generalized_response/TRAIN_CV_REPORT.json",
    "analysis/issue421_generalized_response/VALIDATION_RESULT.json",
    "analysis/issue421_generalized_response/VALIDATION_RESULT.sha256",
    "analysis/issue421_generalized_response/dataset/ARTIFACTS.json",
    "analysis/issue421_generalized_response/dataset/CORPUS_HASHES.json",
    "analysis/issue421_generalized_response/dataset/GENERALIZED_RESPONSE_DATASET.json",
    "analysis/issue421_generalized_response/dataset/GENERALIZED_RESPONSE_DATASET.jsonl",
    "analysis/issue421_generalized_response/dataset/SUMMARY.md",
    "analysis/issue421_generalized_response/model/FIT_REPORT.json",
    "analysis/issue421_generalized_response/model/ARTIFACTS.json",
    "analysis/issue421_generalized_response/model/SUMMARY.md",
    "analysis/issue421_generalized_response/model/candidate_regularized_multinomial_spline.json",
    "analysis/issue421_generalized_response/model/candidate_hierarchical_empirical_bayes_dirichlet.json",
    "analysis/issue421_generalized_response/validation_protocol/ARTIFACTS.json",
    "analysis/issue421_generalized_response/validation_protocol/SUMMARY.md",
    # the workflow and its regenerated audit evidence
    ISSUE_421_WORKFLOW,
    "analysis/workflow_audit/workflows.json",
    "analysis/workflow_audit/active_workflow_dag_v2.json",
    "analysis/workflow_audit/consolidation_decision_v1.json",
    "docs/ci-workflow-dag.md",
)
# Inputs the runner consumes or executes but the issue does not itself change:
# an edit to any of them must still re-run the authoritative surface.
ISSUE_421_EXTERNAL_DEPENDENCIES=(
    "tools/audit_github_workflows.py",
    "tools/audit_active_workflow_dag.py",
    # the shared #204 consolidation-decision guard the runner re-proves last: it
    # belongs to #204/#419, not to the #421 diff, but the runner still executes it.
    *ISSUE_421_CI_SUITES,
    "analysis/issue388_exact_tree/REQUIRED_EXACT_TREE.json",
    "analysis/issue419_hierarchical_tree/raise_sizing_frontiers_v2/RAISE_SIZING_FRONTIER_RESOLUTION.json",
    "tests/fixtures/repro/kts_sb_two_limp_iso4_three_calls.snapshots.json",
)
ISSUE_421_TRIGGER_REQUIRED_PATHS=*ISSUE_421_CHANGED_PATHS,*ISSUE_421_EXTERNAL_DEPENDENCIES


def executed_suites(text: str, required: tuple[str, ...]) -> set[str]:
    """Suites the workflow really runs: a `python3 <suite>` command outside a comment."""
    executable="\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    return {suite for suite in required
            if re.search(r"python3\s+"+re.escape(suite)+r"(?:\s|$)",executable)}


def declared_required_suites(text: str) -> set[str]:
    """The suites the workflow's own `required = (...)` no-op guard asserts it executed."""
    block=re.search(r"required\s*=\s*\((.*?)\)",text,re.S)
    if block is None: return set()
    return set(re.findall(r"'([^']+)'",block.group(1)))


def uncovered_paths(text: str, paths, events: tuple[str, ...]) -> list[tuple[str, str]]:
    """(event, path) pairs a change would land on *without* triggering the runner."""
    triggers=audit.parse_triggers(text.splitlines())
    uncovered=[]
    for event in events:
        patterns=triggers.get(event,{}).get("paths",[])
        for path in paths:
            if not any(dag._glob(pattern,path) for pattern in patterns):
                uncovered.append((event,path))
    return uncovered


def branch_changed_paths() -> list[str] | None:
    """The real branch change surface (working tree included), or None without git history.

    Untracked-but-present files count as surface so a runner added on the branch
    (the workflow file itself) is cross-checked before as well as after the
    orchestrator commits the worktree.
    """
    try:
        base=subprocess.check_output(["git","merge-base","origin/main","HEAD"],cwd=ROOT,text=True,
                                     stderr=subprocess.DEVNULL).strip()
        diff=subprocess.check_output(["git","diff","--name-only",base],cwd=ROOT,text=True,
                                     stderr=subprocess.DEVNULL).split()
        diff+=subprocess.check_output(["git","ls-files","--others","--exclude-standard"],cwd=ROOT,text=True,
                                      stderr=subprocess.DEVNULL).split()
    except (subprocess.CalledProcessError,FileNotFoundError):
        return None
    return sorted({path for path in diff if (ROOT/path).exists()})


def issue_stamped_paths(issue: int) -> set[str] | None:
    """Paths touched by the branch commits stamped `for issue #<issue>`.

    The n8n stack commits one task per issue, so a branch routinely carries more
    than one issue's surface.  Attributing the diff to the issue's own commits
    keeps the completeness guard aimed at the runner under review instead of
    re-asserting an already-merged sibling's filters.
    """
    try:
        base=subprocess.check_output(["git","merge-base","origin/main","HEAD"],cwd=ROOT,text=True,
                                     stderr=subprocess.DEVNULL).strip()
        log=subprocess.check_output(["git","log","--format=%H%x1f%s",f"{base}..HEAD"],cwd=ROOT,text=True,
                                    stderr=subprocess.DEVNULL)
    except (subprocess.CalledProcessError,FileNotFoundError):
        return None
    stamp=f"for issue #{issue}"
    paths:set[str]=set()
    for record in log.splitlines():
        sha,_,subject=record.partition("\x1f")
        if stamp not in subject: continue
        try:
            shown=subprocess.check_output(["git","show","--name-only","--format=",sha],cwd=ROOT,text=True,
                                          stderr=subprocess.DEVNULL)
        except subprocess.CalledProcessError:
            return None
        paths.update(path for path in shown.split() if (ROOT/path).exists())
    return paths


def issue_changed_paths(issue: int) -> list[str] | None:
    """The branch surface carried for one issue, or None without git history."""
    changed=branch_changed_paths()
    stamped=issue_stamped_paths(issue)
    if changed is None or stamped is None: return None
    return sorted(path for path in changed if path in stamped)


def issue421_executed_suites(text: str) -> set[str]:
    """Suites the #421 runner really runs (see `executed_suites`)."""
    return executed_suites(text,ISSUE_421_REQUIRED_SUITES)


def issue421_declared_required_suites(text: str) -> set[str]:
    """The suites the #421 runner's own `required = (...)` no-op guard asserts it executed."""
    return declared_required_suites(text)


def issue421_uncovered_paths(text: str, paths=ISSUE_421_TRIGGER_REQUIRED_PATHS) -> list[tuple[str, str]]:
    """(event, path) pairs a #421 change would land on *without* triggering the runner."""
    return uncovered_paths(text,paths,ISSUE_421_EVENTS)


def issue421_changed_paths() -> list[str] | None:
    """The real #421 change surface, or None when git history is unavailable."""
    return issue_changed_paths(421)

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
        raw=(ROOT/"analysis/workflow_audit/workflows.json").read_bytes()
        regenerated=audit.inventory(ROOT)
        self.assertEqual(json.loads(raw),regenerated)
        # The artifact is regenerated byte-stably, not merely semantically equal:
        # `tools/audit_github_workflows.py --inventory` must reproduce it exactly.
        self.assertEqual(raw,(json.dumps(regenerated,indent=2,sort_keys=True)+"\n").encode(),
                         "analysis/workflow_audit/workflows.json is not byte-stable")

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
        """Completeness: the filters must cover the real #419 surface, not only a curated list."""
        changed=issue419_changed_paths()
        if changed is None:
            self.skipTest("git history unavailable (shallow checkout): set fetch-depth: 0 to enforce this")
        if not changed:
            # #419 is already merged into origin/main, so this branch carries none of
            # its commits and none of its surface: there is nothing to cross-check here.
            # The `test_issue419_*` guards above/below still pin the runner itself.
            self.skipTest("branch carries no #419-stamped commit: surface cross-check not applicable")
        text=(ROOT/ISSUE_419_WORKFLOW).read_text()
        self.assertEqual([],issue419_uncovered_paths(text,changed),
                         "the #419 change surface exposes paths the runner never triggers on")
        # The curated manifest must stay a subset of the real surface, so it can never
        # assert coverage for a path the issue does not actually ship.
        fabricated=set(ISSUE_419_CHANGED_PATHS)-set(changed)
        self.assertEqual(set(),fabricated,f"manifest claims paths outside the #419 surface: {sorted(fabricated)}")

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

    def test_issue419_workflow_executes_every_declared_suite(self):
        """The workflow must run every declared suite as a real command, not a declaration.

        The declared set is the union ``ISSUE_419_SUITES ∪ ISSUE_419_EXTRA_SUITES`` (the
        #419 suites plus the aggregate contract and this audit guard) extended with the
        shared audit chain (``ISSUE_419_CI_SUITES``): no suite the branch ships may stay
        silently unexecuted.
        """
        text=(ROOT/ISSUE_419_WORKFLOW).read_text()
        declared=set(ISSUE_419_SUITES)|set(ISSUE_419_EXTRA_SUITES)
        self.assertEqual(declared-set(ISSUE_419_REQUIRED_SUITES),set(),
                         "the required set must cover the declared union")
        self.assertEqual(set(ISSUE_419_REQUIRED_SUITES)-issue419_executed_suites(text),set())
        # Each suite is executed independently so a failure cannot be masked by a later step.
        for suite in ISSUE_419_REQUIRED_SUITES:
            with self.subTest(suite=suite):
                self.assertRegex(text,r"python3\s+"+re.escape(suite)+r"(?:\s|$)")

    def test_issue419_noop_guard_tuple_mirrors_the_declared_suites(self):
        """The workflow's own `required` tuple must mirror the suites this test declares.

        The inline no-op guard is the runtime half of the check; if a suite were added to
        the declared union but not to the workflow tuple (or vice versa) the guard would
        stop proving that the runner executes it.
        """
        text=(ROOT/ISSUE_419_WORKFLOW).read_text()
        declared=set(ISSUE_419_SUITES)|set(ISSUE_419_EXTRA_SUITES)
        required=issue419_declared_required_suites(text)
        self.assertTrue(required,f"no `required = (...)` tuple found in {ISSUE_419_WORKFLOW}")
        self.assertEqual(declared-required,set(),
                         "the workflow no-op guard tuple is missing declared suites")
        self.assertEqual(set(ISSUE_419_CI_SUITES)-required,set(),
                         "the workflow no-op guard tuple is missing the shared audit chain")

    def test_issue419_noop_workflow_is_detected(self):
        """Negative guard: a workflow that only declares the suites in `paths` must be flagged."""
        text=(ROOT/ISSUE_419_WORKFLOW).read_text()
        declaration_only="\n".join(
            line for line in text.splitlines()
            if line.lstrip().startswith(("-","'")) or line.startswith("on:") or line.startswith("  paths:"))
        self.assertEqual(set(),issue419_executed_suites(declaration_only))
        # Dropping a single executed command is also detected, so the guard cannot silently pass.
        for suite in ISSUE_419_REQUIRED_SUITES:
            with self.subTest(suite=suite):
                dropped="\n".join(line for line in text.splitlines() if suite not in line)
                self.assertIn(suite,set(ISSUE_419_REQUIRED_SUITES)-issue419_executed_suites(dropped))

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

    # ------------------------------------------------------------------
    # Issue #421: the same two properties, asserted on its own runner.
    # ------------------------------------------------------------------
    def test_issue421_changed_paths_are_all_covered_by_the_workflow(self):
        """Every #421 path must trigger the authoritative runner on push and on pull_request."""
        text=(ROOT/ISSUE_421_WORKFLOW).read_text()
        triggers=audit.parse_triggers(text.splitlines())
        self.assertIn("push",triggers,ISSUE_421_WORKFLOW)
        self.assertIn("pull_request",triggers,ISSUE_421_WORKFLOW)
        for changed in ISSUE_421_TRIGGER_REQUIRED_PATHS:
            self.assertTrue((ROOT/changed).exists(),f"declared #421 path is missing: {changed}")
        self.assertEqual([],issue421_uncovered_paths(text))

    def test_issue421_trigger_paths_cover_the_issue_surface(self):
        """Completeness: the filters must cover the real #421 surface, not only a curated list."""
        surface=branch_changed_paths()
        changed=issue421_changed_paths()
        if surface is None or changed is None:
            self.skipTest("git history unavailable (shallow checkout): set fetch-depth: 0 to enforce this")
        # The curated manifest must stay inside the real branch surface, so it can
        # never assert coverage for a path the issue does not actually ship.
        fabricated=set(ISSUE_421_CHANGED_PATHS)-set(surface)
        self.assertEqual(set(),fabricated,
                         f"manifest claims paths outside the #421 branch surface: {sorted(fabricated)}")
        if not changed:
            self.skipTest("branch carries no #421-stamped commit: surface cross-check not applicable")
        text=(ROOT/ISSUE_421_WORKFLOW).read_text()
        self.assertEqual([],issue421_uncovered_paths(text,changed),
                         "the #421 change surface exposes paths the runner never triggers on")

    def test_issue421_trigger_drift_and_substitution_are_detected(self):
        """Negative guard: dropping or swapping a #421 trigger pattern must be detected."""
        text=(ROOT/ISSUE_421_WORKFLOW).read_text()
        # (a) drift: a narrower test filter must not cover the shipped preflight suite.
        drifted=text.replace("      - 'tests/simulation/test_issue421_preflight.py'\n",
                             "      - 'tests/simulation/test_issue421_preflight_v2.py'\n")
        self.assertIn(("push","tests/simulation/test_issue421_preflight.py"),
                      issue421_uncovered_paths(drifted))
        # (b) substitution: a nearby path that looks right but is not the shipped one.
        substituted=text.replace("      - 'tests/preflop/test_generalized_response_*.py'\n",
                                 "      - 'tests/preflop/test_generalized_response_model.py'\n")
        self.assertIn(("pull_request","tests/preflop/test_generalized_response_runtime.py"),
                      issue421_uncovered_paths(substituted))
        # (c) a silently-renamed evidence directory must also be flagged.
        renamed=text.replace("'analysis/issue421_generalized_response/**'",
                             "'analysis/issue421_generalized_responses/**'")
        self.assertIn(("push","analysis/issue421_generalized_response/DECISION.json"),
                      issue421_uncovered_paths(renamed))

    def test_issue421_workflow_executes_every_declared_suite(self):
        """The #421 runner must execute every declared suite as a real command.

        The declared set is the union ``ISSUE_421_SUITES ∪ ISSUE_421_EXTRA_SUITES``
        (the T1..T11 suites plus the T12 evidence bundle and this audit guard)
        extended with the shared audit chain (``ISSUE_421_CI_SUITES``): no suite
        the branch ships may stay silently unexecuted.
        """
        text=(ROOT/ISSUE_421_WORKFLOW).read_text()
        declared=set(ISSUE_421_SUITES)|set(ISSUE_421_EXTRA_SUITES)
        self.assertEqual(declared-set(ISSUE_421_REQUIRED_SUITES),set(),
                         "the required set must cover the declared union")
        self.assertEqual(set(ISSUE_421_REQUIRED_SUITES)-issue421_executed_suites(text),set())
        # Each suite is executed independently so a failure cannot be masked by a later step.
        for suite in ISSUE_421_REQUIRED_SUITES:
            with self.subTest(suite=suite):
                self.assertRegex(text,r"python3\s+"+re.escape(suite)+r"(?:\s|$)")

    def test_issue421_noop_guard_tuple_mirrors_the_declared_suites(self):
        """The #421 runner's own `required` tuple must mirror the suites declared here."""
        text=(ROOT/ISSUE_421_WORKFLOW).read_text()
        declared=set(ISSUE_421_SUITES)|set(ISSUE_421_EXTRA_SUITES)
        required=issue421_declared_required_suites(text)
        self.assertTrue(required,f"no `required = (...)` tuple found in {ISSUE_421_WORKFLOW}")
        self.assertEqual(declared-required,set(),
                         "the workflow no-op guard tuple is missing declared suites")
        self.assertEqual(set(ISSUE_421_CI_SUITES)-required,set(),
                         "the workflow no-op guard tuple is missing the shared audit chain")

    def test_issue421_noop_workflow_is_detected(self):
        """Negative guard: a workflow that only declares the #421 suites in `paths` must be flagged."""
        text=(ROOT/ISSUE_421_WORKFLOW).read_text()
        declaration_only="\n".join(
            line for line in text.splitlines()
            if line.lstrip().startswith(("-","'")) or line.startswith("on:") or line.startswith("  paths:"))
        self.assertEqual(set(),issue421_executed_suites(declaration_only))
        # Dropping a single executed command is also detected, so the guard cannot silently pass.
        for suite in ISSUE_421_REQUIRED_SUITES:
            with self.subTest(suite=suite):
                dropped="\n".join(line for line in text.splitlines() if suite not in line)
                self.assertIn(suite,set(ISSUE_421_REQUIRED_SUITES)-issue421_executed_suites(dropped))

    def test_issue421_workflow_is_read_only_and_registered(self):
        """The #421 runner publishes no artifact and never widens the write surface."""
        text=(ROOT/ISSUE_421_WORKFLOW).read_text()
        self.assertIn("permissions:\n  contents: read",text)
        for forbidden in ("upload-artifact","git push","pull_request_target","gh release create","wrangler deploy"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden,text)
        row=next(r for r in audit.inventory(ROOT)["workflows"] if r["path"]==ISSUE_421_WORKFLOW)
        self.assertTrue(row["automatic"])
        self.assertEqual(row["triggers"],["push","pull_request","workflow_dispatch"])
        self.assertEqual(row["artifacts"],[])

    def test_issue421_decision_artifact_classifies_the_workflow_as_safe(self):
        decision=json.loads((ROOT/dag.DECISION).read_text())
        row=next(r for r in decision["workflows"] if r["path"]==ISSUE_421_WORKFLOW)
        self.assertEqual("READ_ONLY",row["side_effect_class"])
        self.assertIs(row["fail_closed_safe"],True)
        self.assertEqual("SAFE_CANDIDATE_NOT_APPLIED",row["recommendation_state"])
        self.assertTrue(row["blockers"])

    def test_dag_evidence_is_regenerable_and_covers_the_issue_runners(self):
        """DAG half of the committed-evidence parity: the versioned DAG, its decision artifact
        and its rendered Markdown must all be the deterministic output of the generators at
        HEAD, and every per-issue runner (#419, #421) must appear as an active, read-only
        workflow.

        ``test_committed_inventory_is_regenerable`` pins the inventory and each runner's path
        filters pin its triggers; this ties the two together so a workflow added to the
        checkout can never silently drift out of the DAG evidence or its documentation.
        """
        inventory_bytes=(ROOT/"analysis/workflow_audit/workflows.json").read_bytes()
        data=dag.build(); decision=dag.build_decision(data)
        self.assertEqual(data,json.loads((ROOT/dag.OUTPUT).read_text()),f"{dag.OUTPUT} is stale")
        self.assertEqual(decision,json.loads((ROOT/dag.DECISION).read_text()),f"{dag.DECISION} is stale")
        self.assertEqual(dag.markdown(data,decision),(ROOT/dag.DOC).read_text(),f"{dag.DOC} is stale")
        # The DAG is bound to the committed inventory, not to a private copy of it.
        self.assertEqual(hashlib.sha256(inventory_bytes).hexdigest(),data["inventory_sha256"])
        inventory=json.loads(inventory_bytes)
        self.assertEqual(inventory["aggregate"]["automatic_trigger_workflows"],data["active_workflow_count"])
        self.assertEqual(inventory["aggregate"]["manual_only_workflows"],data["manual_only_count"])
        for path in (ISSUE_419_WORKFLOW,ISSUE_421_WORKFLOW):
            with self.subTest(path=path):
                # The new workflow is active (not quarantined) and classified like the inventory does.
                self.assertNotIn(path,data["excluded_manual_only_workflows"])
                inventory_row=next(r for r in inventory["workflows"] if r["path"]==path)
                self.assertTrue(inventory_row["automatic"])
                self.assertEqual("current",inventory_row["lifecycle"])
                dag_row=next((r for r in data["workflows"] if r["path"]==path),None)
                self.assertIsNotNone(dag_row,f"{path} missing from the active DAG")
                self.assertEqual(inventory_row["role"],dag_row["role"])
                self.assertEqual("validation_or_utility",dag_row["role"])
                self.assertEqual("READ_ONLY",dag_row["side_effect_class"])
                self.assertTrue(dag_row["concurrency_recommendation"]["safe_candidate_for_future_cancellation_change"])

if __name__=="__main__": unittest.main()

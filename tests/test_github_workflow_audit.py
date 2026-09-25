#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
import hashlib, json, shutil, sys, tempfile, unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools import audit_github_workflows as audit

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
if __name__=="__main__": unittest.main()

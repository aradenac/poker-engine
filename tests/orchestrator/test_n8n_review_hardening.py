from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]


def load(name: str):
    path = ROOT / "ops" / "n8n" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


review_events = load("review_events")
state_ops = load("state_ops")
rebase_resolver = load("rebase_resolver")
deploy = load("deploy")


class ReviewEventTests(unittest.TestCase):
    def test_review_id_below_legacy_comment_watermark_is_detected(self) -> None:
        event = {
            "kind": "review",
            "id": 5_331_011_364,
            "event_key": "review:5331011364",
            "fingerprint": "a" * 64,
            "actionable": True,
            "commit_id": "head",
            "updated_at": "2026-09-27T15:57:55Z",
        }
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / "ledger.json"
            with mock.patch.object(review_events, "_reviews", return_value=[event]), mock.patch.object(
                review_events, "_review_comments", return_value=[]
            ):
                result = review_events.collect("aradenac/poker-engine", 426, ledger, "head")
            self.assertTrue(result["has_actionable_reviews"])
            self.assertTrue(result["pending_events"][0]["targets_current_head"])

    def test_ack_is_idempotent_and_edit_reopens_event(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / "ledger.json"
            event = {
                "kind": "review",
                "id": 1,
                "event_key": "review:1",
                "fingerprint": "1" * 64,
                "actionable": True,
                "commit_id": "head",
                "updated_at": "t1",
            }
            review_events.acknowledge(ledger, 10, [event], "PLANNED")
            with mock.patch.object(review_events, "_reviews", return_value=[event]), mock.patch.object(
                review_events, "_review_comments", return_value=[]
            ):
                self.assertFalse(review_events.collect("o/r", 10, ledger, "head")["pending_events"])
            edited = dict(event, fingerprint="2" * 64, updated_at="t2")
            with mock.patch.object(review_events, "_reviews", return_value=[edited]), mock.patch.object(
                review_events, "_review_comments", return_value=[]
            ):
                self.assertEqual(len(review_events.collect("o/r", 10, ledger, "head")["pending_events"]), 1)

    def test_review_actionability_is_explicit(self) -> None:
        self.assertTrue(review_events.ACTIONABLE_REVIEW.search("## Review — NEEDS_FIXES"))
        self.assertIsNone(review_events.ACTIONABLE_REVIEW.search("CI infrastructure blocker resolved"))


class StateOpsTests(unittest.TestCase):
    def test_untrusted_reason_remains_data(self) -> None:
        dangerous = "`touch /tmp/nope` $(false) ' \" <tag>\nsecond line"
        with tempfile.TemporaryDirectory() as directory:
            pointer = Path(directory) / "active_run.json"
            pointer.write_text('{"phase":"WORKING"}\n', encoding="utf-8")
            payload = {
                "pointer": str(pointer),
                "reason": dangerous,
                "stage": "REVIEW",
                "repo": "owner/repo",
                "issue_number": 1,
                "claim_comment_id": 0,
            }
            with mock.patch.object(state_ops, "_gh", return_value="") as gh:
                result = state_ops.mark_needs_human(payload)
            self.assertEqual(result["status"], "OK")
            self.assertEqual(json.loads(pointer.read_text())["terminal_reason"], dangerous)
            self.assertEqual(gh.call_args.args[0][0:2], ["issue", "comment"])

    def test_resume_is_explicit_and_preserves_context(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pointer = Path(directory) / "active_run.json"
            pointer.write_text(json.dumps({"phase":"INTEGRATION_FAILED_NEEDS_HUMAN","merge_gate_context":{"pr_number":428}}))
            result = state_ops.resume({"pointer":str(pointer),"mode":"ci"})
            self.assertEqual(result["phase"], "CI_PENDING")
            saved = json.loads(pointer.read_text())
            self.assertEqual(saved["merge_gate_context"]["pr_number"], 428)
            self.assertIsNone(saved["terminal_reason"])

    def test_needs_human_can_preserve_ci_resume_context(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pointer = Path(directory) / "active_run.json"
            pointer.write_text('{"phase":"CI_PENDING"}\n', encoding="utf-8")
            context = {"pr_number": 428, "reviewed_head_sha": "abc"}
            payload = {
                "pointer": str(pointer),
                "phase": "CI_FAILED_NEEDS_HUMAN",
                "reason": "CI failed",
                "stage": "CI_GATE",
                "repo": "owner/repo",
                "issue_number": 1,
                "claim_comment_id": 0,
                "merge_gate_context": context,
            }
            with mock.patch.object(state_ops, "_gh", return_value=""):
                state_ops.mark_needs_human(payload)
            saved = json.loads(pointer.read_text())
            self.assertEqual(saved["phase"], "CI_FAILED_NEEDS_HUMAN")
            self.assertEqual(saved["merge_gate_context"], context)


class DeployTests(unittest.TestCase):
    def test_contract_validator_upgrade_is_idempotent(self) -> None:
        source = "\n\n".join(deploy.OLD_CLAIM_VALIDATION.values()) + "\n"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "validator.py"
            backup = Path(directory) / "backup"
            path.write_text(source, encoding="utf-8")
            self.assertTrue(deploy.patch_contract_validator(path, apply=True, backup_root=backup))
            self.assertTrue((backup / "validator.py.before").is_file())
            self.assertFalse(deploy.patch_contract_validator(path))
            updated = path.read_text(encoding="utf-8")
            self.assertIn("state_ops.py mark-needs-human", updated)


class RebaseResolverTests(unittest.TestCase):
    def git(self, cwd: Path, *args: str) -> str:
        return subprocess.run(["git", "-C", str(cwd), *args], check=True, text=True, capture_output=True).stdout.strip()

    def test_conflict_is_resolved_without_agent_git_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            remote = root / "remote.git"
            seed = root / "seed"
            work = root / "work"
            subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
            subprocess.run(["git", "init", "-b", "main", str(seed)], check=True, capture_output=True)
            self.git(seed, "config", "user.email", "test@example.com")
            self.git(seed, "config", "user.name", "Test")
            (seed / "conflict.txt").write_text("base\n")
            self.git(seed, "add", "conflict.txt")
            self.git(seed, "commit", "-m", "base")
            self.git(seed, "remote", "add", "origin", str(remote))
            self.git(seed, "push", "-u", "origin", "main")
            self.git(seed, "checkout", "-b", "feature")
            (seed / "conflict.txt").write_text("feature\n")
            (seed / "companion.txt").write_text("feature companion\n")
            self.git(seed, "add", "conflict.txt", "companion.txt")
            self.git(seed, "commit", "-m", "feature")
            self.git(seed, "push", "-u", "origin", "feature")
            feature_head = self.git(seed, "rev-parse", "HEAD")
            self.git(seed, "checkout", "main")
            (seed / "conflict.txt").write_text("main\n")
            self.git(seed, "commit", "-am", "main")
            self.git(seed, "push", "origin", "main")
            subprocess.run(["git", "clone", "--branch", "feature", str(remote), str(work)], check=True, capture_output=True)
            self.git(work, "config", "user.email", "test@example.com")
            self.git(work, "config", "user.name", "Test")

            def resolve(repo: Path, issue_dir: Path, paths: set[str], attempt: int):
                self.assertEqual(paths, {"conflict.txt"})
                (repo / "conflict.txt").write_text("main + feature\n")
                return {"returncode": 0, "stdout": "ok", "stderr": ""}

            with mock.patch.object(rebase_resolver, "_agent", side_effect=resolve):
                result = rebase_resolver.resolve(work, root / "issue", "feature", 5, 2)
            self.assertEqual(result["status"], "OK")
            inner = json.loads(result["stdout"])
            self.assertEqual(inner["expected_remote_head"], feature_head)
            self.assertEqual((work / "conflict.txt").read_text(), "main + feature\n")
            self.assertEqual((work / "companion.txt").read_text(), "feature companion\n")
            self.assertTrue(self.git(work, "merge-base", "--is-ancestor", "origin/main", "HEAD") == "")


if __name__ == "__main__":
    unittest.main()

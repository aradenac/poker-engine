#!/usr/bin/env python3
from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.validate_release_handoff import load_json, validate_handoff  # noqa: E402

CONTRACT = load_json(ROOT / "training/automation/RELEASE_HANDOFF_CONTRACT.json")
H64 = "a" * 64
B64 = "b" * 64
C64 = "c" * 64
D64 = "d" * 64
E40 = "e" * 40
F40 = "f" * 40


def common(outcome: str, state: str) -> dict:
    before = {
        "site_release": {"path": "site/RELEASE.json", "sha256": H64},
        "population_registry": {"path": "training/populations/registry.json", "sha256": B64},
    }
    return {
        "schema": "poker-release-handoff/v1",
        "outcome": outcome,
        "state": state,
        "population_id": "pokerstars_nlhe_100-200_zoom_play_6max_v1",
        "cycle_run_id": "fixture-cycle",
        "snapshot_sha256": C64,
        "source_commit_sha": E40,
        "cycle_decision": {"path": "training/populations/p/runs/r/DECISION.json", "sha256": D64},
        "production_before": before,
        "production_after": copy.deepcopy(before),
        "promotion_authorized": outcome == "PROMOTE",
    }


def promote(state: str) -> dict:
    row = common("PROMOTE", state)
    row["promotion"] = {
        "plan": {"path": "training/populations/p/runs/r/PROMOTION.json", "sha256": H64},
        "candidate_pack": {"path": "user/artifacts/p-v1/bundle.json", "sha256": B64},
        "candidate_site_release": {"path": "training/populations/p/runs/r/RELEASE.json", "sha256": C64},
        "expected_release_commit_sha": F40,
    }
    row["rollback"] = {
        "site_release_sha256": H64,
        "population_registry_sha256": B64,
    }
    row["deployment"] = {
        "provider": "CLOUDFLARE_WORKERS",
        "static_root": "site",
        "wrangler_config": {"path": "wrangler.jsonc", "sha256": D64},
        "production_url": "https://poker-engine.arad-chatgpt-compositeur-repas.workers.dev",
        "attempted": state != "PREPARED",
    }
    return row


def assert_pass(row: dict, *, delivered: bool) -> None:
    result = validate_handoff(row, CONTRACT)
    assert result["status"] == "PASS", result
    assert result["delivered"] is delivered, result


def assert_fail(row: dict, fragment: str) -> None:
    result = validate_handoff(row, CONTRACT)
    assert result["status"] == "FAIL", result
    assert any(fragment.lower() in error.lower() for error in result["errors"]), result


def test_retain_is_terminal_only_when_production_is_proven_unchanged() -> None:
    row = common("RETAIN", "VERIFIED_NO_PUBLICATION")
    row["reason"] = "VALIDATION gate retained reference"
    row["deployment"] = {"attempted": False}
    assert_pass(row, delivered=True)
    changed = copy.deepcopy(row)
    changed["production_after"]["site_release"]["sha256"] = C64
    assert_fail(changed, "preserve exact production")


def test_noop_and_blocked_never_authorize_deployment() -> None:
    for outcome in ("NO_OP", "BLOCKED"):
        row = common(outcome, "VERIFIED_NO_PUBLICATION")
        row["reason"] = "nothing publishable"
        row["deployment"] = {"attempted": False}
        assert_pass(row, delivered=True)
        bad = copy.deepcopy(row)
        bad["deployment"]["attempted"] = True
        assert_fail(bad, "cannot attempt deployment")


def test_prepared_promotion_is_valid_but_not_delivered() -> None:
    assert_pass(promote("PREPARED"), delivered=False)


def test_preview_url_cannot_masquerade_as_production() -> None:
    row = promote("PREPARED")
    row["deployment"]["production_url"] = "https://b9d68b8a-poker-engine.arad-chatgpt-compositeur-repas.workers.dev"
    assert_fail(row, "canonical production")


def test_verified_live_requires_exact_commit_release_and_all_probes() -> None:
    row = promote("VERIFIED_LIVE")
    row["deployment"].update({
        "deployed_commit_sha": F40,
        "provider_build_id": "build-123",
        "provider_version_id": "version-123",
    })
    row["live_verification"] = {
        "production_url": row["deployment"]["production_url"],
        "observed_commit_sha": F40,
        "observed_site_release_sha256": C64,
        "checked_at": "2026-09-17T10:00:00Z",
        "probes": [
            {"id": probe, "status": "PASS"}
            for probe in ("release_identity", "index", "replayer", "trainer", "hero_ranges", "required_assets")
        ],
    }
    assert_pass(row, delivered=True)
    wrong_commit = copy.deepcopy(row)
    wrong_commit["live_verification"]["observed_commit_sha"] = E40
    assert_fail(wrong_commit, "observed commit")
    failed_probe = copy.deepcopy(row)
    failed_probe["live_verification"]["probes"][2]["status"] = "FAIL"
    assert_fail(failed_probe, "replayer did not pass")


def test_failed_publication_is_terminal_only_after_exact_rollback() -> None:
    row = promote("ROLLED_BACK")
    row["rollback"].update({
        "performed": True,
        "site_release_sha256_after": H64,
        "population_registry_sha256_after": B64,
    })
    assert_pass(row, delivered=False)
    broken = copy.deepcopy(row)
    broken["rollback"]["site_release_sha256_after"] = C64
    assert_fail(broken, "restore site release")


def test_published_unverified_can_never_be_delivered() -> None:
    assert_pass(promote("PUBLISHED_UNVERIFIED"), delivered=False)


def main() -> None:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
    print(f"release handoff tests: {len(tests)} passed")


if __name__ == "__main__":
    main()

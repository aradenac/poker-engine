#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.training.build_promote_release_handoff import (  # noqa: E402
    build_prepared_promote_handoff,
    record_published_handoff,
    record_rolled_back_handoff,
    record_verified_live_handoff,
)
from tools.training.build_release_handoff import sha256_file  # noqa: E402
from tools.validate_release_handoff import load_json  # noqa: E402

CONTRACT = ROOT / "training/automation/RELEASE_HANDOFF_CONTRACT.json"
POPULATION = "pokerstars_nlhe_100-200_zoom_play_6max_v1"
EXPECTED_COMMIT = "a" * 40


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def fixture(root: Path, *, registry_last: bool = True):
    site_release = root / "site/RELEASE.json"
    registry = root / "training/populations/registry.json"
    candidate_release = root / "staging/RELEASE.json"
    candidate_registry = root / "staging/registry.json"
    candidate_pack = root / "staging/population-pack.zip"
    cycle_decision = root / "training/runs/cycle/DECISION.json"
    snapshot = root / "training/datasets/snapshot.zip"
    wrangler = root / "wrangler.jsonc"
    plan = root / "training/runs/cycle/PROMOTION_PLAN.json"

    write_json(site_release, {
        "schema": "poker-site-release/v3",
        "version": "old",
        "publication_verification": {"status": "UNVERIFIED_LIVE"},
    })
    write_json(registry, {"schema": "fixture-registry", "active": "old"})
    write_json(candidate_release, {
        "schema": "poker-site-release/v3",
        "version": "candidate",
        "publication_verification": {"status": "UNVERIFIED_LIVE"},
    })
    write_json(candidate_registry, {"schema": "fixture-registry", "active": "candidate"})
    candidate_pack.parent.mkdir(parents=True, exist_ok=True)
    candidate_pack.write_bytes(b"candidate-pack-v1")
    write_json(cycle_decision, {
        "population_id": POPULATION,
        "outcome": "PROMOTE",
        "promotion_authorized": True,
    })
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot.write_bytes(b"immutable-snapshot")
    wrangler.write_text('{"name":"poker-engine","assets":{"directory":"./site"}}\n', encoding="utf-8")

    release_op = {
        "id": "site-release",
        "source": candidate_release.relative_to(root).as_posix(),
        "destination": site_release.relative_to(root).as_posix(),
        "source_sha256": sha256_file(candidate_release),
        "destination_sha256_before": sha256_file(site_release),
    }
    registry_op = {
        "id": "population-registry",
        "source": candidate_registry.relative_to(root).as_posix(),
        "destination": registry.relative_to(root).as_posix(),
        "source_sha256": sha256_file(candidate_registry),
        "destination_sha256_before": sha256_file(registry),
    }
    operations = [release_op, registry_op] if registry_last else [registry_op, release_op]
    write_json(plan, {"schema": "poker-atomic-promotion/v1", "operations": operations})
    return {
        "root": root,
        "site_release": site_release,
        "registry": registry,
        "candidate_release": candidate_release,
        "candidate_pack": candidate_pack,
        "cycle_decision": cycle_decision,
        "snapshot": snapshot,
        "wrangler": wrangler,
        "plan": plan,
    }


def prepare(paths):
    return build_prepared_promote_handoff(
        root=paths["root"],
        population_id=POPULATION,
        cycle_run_id="cycle-001",
        cycle_decision_path=paths["cycle_decision"],
        snapshot=paths["snapshot"],
        snapshot_sha256=None,
        site_release_path=paths["site_release"],
        population_registry_path=paths["registry"],
        source_commit_sha="b" * 40,
        promotion_plan_path=paths["plan"],
        candidate_pack_path=paths["candidate_pack"],
        candidate_site_release_path=paths["candidate_release"],
        expected_release_commit_sha=EXPECTED_COMMIT,
        wrangler_config_path=paths["wrangler"],
        production_url="https://poker-engine.workers.dev",
        contract_path=CONTRACT,
    )


def deployment_evidence():
    return {
        "deployed_commit_sha": EXPECTED_COMMIT,
        "provider_build_id": "build-123",
        "provider_version_id": "version-456",
    }


def live_evidence(candidate_release_sha: str):
    probes = [
        {"id": probe_id, "status": "PASS"}
        for probe_id in (
            "release_identity",
            "index",
            "replayer",
            "trainer",
            "hero_ranges",
            "required_assets",
        )
    ]
    return {
        "production_url": "https://poker-engine.workers.dev",
        "observed_commit_sha": EXPECTED_COMMIT,
        "observed_site_release_sha256": candidate_release_sha,
        "checked_at": "2026-09-18T20:00:00Z",
        "probes": probes,
    }


def test_prepared_promote_handoff_is_content_addressed_and_not_delivered() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        paths = fixture(Path(tmp))
        document, validation = prepare(paths)
        assert document["state"] == "PREPARED"
        assert document["outcome"] == "PROMOTE"
        assert document["promotion_authorized"] is True
        assert document["deployment"]["attempted"] is False
        assert document["promotion"]["candidate_site_release"]["sha256"] == sha256_file(paths["candidate_release"])
        assert document["rollback"]["site_release_sha256"] == sha256_file(paths["site_release"])
        assert document["rollback"]["population_registry_sha256"] == sha256_file(paths["registry"])
        assert validation["status"] == "PASS"
        assert validation["delivered"] is False


def test_registry_promotion_must_be_last() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        paths = fixture(Path(tmp), registry_last=False)
        try:
            prepare(paths)
        except ValueError as exc:
            assert "final promotion operation" in str(exc)
        else:
            raise AssertionError("registry-before-release plan must fail closed")


def test_preview_worker_url_is_not_production_evidence() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        paths = fixture(Path(tmp))
        try:
            build_prepared_promote_handoff(
                root=paths["root"],
                population_id=POPULATION,
                cycle_run_id="cycle-001",
                cycle_decision_path=paths["cycle_decision"],
                snapshot=paths["snapshot"],
                snapshot_sha256=None,
                site_release_path=paths["site_release"],
                population_registry_path=paths["registry"],
                source_commit_sha="b" * 40,
                promotion_plan_path=paths["plan"],
                candidate_pack_path=paths["candidate_pack"],
                candidate_site_release_path=paths["candidate_release"],
                expected_release_commit_sha=EXPECTED_COMMIT,
                wrangler_config_path=paths["wrangler"],
                production_url="https://preview.poker-engine.workers.dev",
                contract_path=CONTRACT,
            )
        except ValueError as exc:
            assert "canonical production" in str(exc)
        else:
            raise AssertionError("preview URL must not be accepted as production")


def test_published_unverified_is_valid_but_not_delivered() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        paths = fixture(Path(tmp))
        prepared, _ = prepare(paths)
        published, validation = record_published_handoff(
            prepared,
            deployment_evidence(),
            load_json(CONTRACT),
        )
        assert published["state"] == "PUBLISHED_UNVERIFIED"
        assert published["deployment"]["attempted"] is True
        assert validation["status"] == "PASS"
        assert validation["delivered"] is False


def test_verified_live_requires_all_exact_probes_and_is_delivered() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        paths = fixture(Path(tmp))
        prepared, _ = prepare(paths)
        live = live_evidence(sha256_file(paths["candidate_release"]))
        verified, validation = record_verified_live_handoff(
            prepared,
            deployment_evidence(),
            live,
            load_json(CONTRACT),
        )
        assert verified["state"] == "VERIFIED_LIVE"
        assert validation["status"] == "PASS"
        assert validation["delivered"] is True

        bad = live_evidence(sha256_file(paths["candidate_release"]))
        bad["probes"] = [row for row in bad["probes"] if row["id"] != "trainer"]
        try:
            record_verified_live_handoff(
                prepared,
                deployment_evidence(),
                bad,
                load_json(CONTRACT),
            )
        except ValueError as exc:
            assert "missing live probe trainer" in str(exc)
        else:
            raise AssertionError("VERIFIED_LIVE without trainer probe must fail")


def test_rolled_back_requires_exact_production_before_hashes() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        paths = fixture(Path(tmp))
        prepared, _ = prepare(paths)
        rollback = {
            "performed": True,
            "site_release_sha256_after": prepared["production_before"]["site_release"]["sha256"],
            "population_registry_sha256_after": prepared["production_before"]["population_registry"]["sha256"],
        }
        rolled, validation = record_rolled_back_handoff(
            prepared,
            deployment_evidence(),
            rollback,
            load_json(CONTRACT),
        )
        assert rolled["state"] == "ROLLED_BACK"
        assert validation["status"] == "PASS"
        assert validation["delivered"] is False

        bad = dict(rollback)
        bad["site_release_sha256_after"] = "0" * 64
        try:
            record_rolled_back_handoff(
                prepared,
                deployment_evidence(),
                bad,
                load_json(CONTRACT),
            )
        except ValueError as exc:
            assert "rollback did not restore site release identity" in str(exc)
        else:
            raise AssertionError("rollback hash drift must fail")


def main() -> None:
    tests = [
        value
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    for test in tests:
        test()
    print(f"PROMOTE release-handoff tests: {len(tests)} passed")


if __name__ == "__main__":
    main()

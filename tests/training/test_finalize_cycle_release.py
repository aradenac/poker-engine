#!/usr/bin/env python3
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from tools.training.build_release_handoff import sha256_file
from tools.training.finalize_cycle_release import (
    classify_release_outcome,
    finalize_cycle_release,
    write_new_handoff,
)

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "training/automation/RELEASE_HANDOFF_CONTRACT.json"
POPULATION = "pokerstars_nlhe_100-200_zoom_play_6max_v1"


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def fixture(root: Path, decision):
    release = root / "site/RELEASE.json"
    registry = root / "training/populations/registry.json"
    snapshot = root / "training/datasets/snapshot.zip"
    decision_path = root / "training/runs/cycle/DECISION.json"
    wrangler = root / "wrangler.jsonc"
    write_json(release, {
        "schema": "poker-site-release/v3",
        "version": "baseline",
        "publication_verification": {"status": "UNVERIFIED_LIVE"},
    })
    write_json(registry, {"schema": "fixture-registry", "active": "baseline"})
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot.write_bytes(b"immutable-snapshot")
    write_json(decision_path, decision)
    wrangler.write_text(
        '{"name":"poker-engine","assets":{"directory":"./site"}}\n',
        encoding="utf-8",
    )
    return {
        "release": release,
        "registry": registry,
        "snapshot": snapshot,
        "decision": decision_path,
        "wrangler": wrangler,
    }


def finalize(root: Path, paths, **kwargs):
    return finalize_cycle_release(
        root=root,
        population_id=POPULATION,
        cycle_run_id="cycle-001",
        cycle_decision_path=paths["decision"],
        snapshot=paths["snapshot"],
        snapshot_sha256=None,
        site_release_path=paths["release"],
        population_registry_path=paths["registry"],
        source_commit_sha="b" * 40,
        reason=None,
        promotion_plan_path=kwargs.get("promotion_plan"),
        candidate_pack_path=kwargs.get("candidate_pack"),
        candidate_site_release_path=kwargs.get("candidate_release"),
        expected_release_commit_sha=kwargs.get("expected_commit"),
        wrangler_config_path=paths["wrangler"],
        production_url=kwargs.get("production_url"),
        contract_path=CONTRACT,
    )


def test_classifies_only_one_terminal_outcome():
    assert classify_release_outcome({"outcome": "NO_OP_NO_NEW_HANDS"}) == "NO_OP"
    assert classify_release_outcome({"decision": "RETAIN_REFERENCE"}) == "RETAIN"
    assert classify_release_outcome({"status": "BLOCKED_MISSING_INPUT"}) == "BLOCKED"
    assert classify_release_outcome({"outcome": "PROMOTE"}) == "PROMOTE"


def test_conflicting_promote_and_blocked_fails_closed():
    try:
        classify_release_outcome({"status": "BLOCKED", "promotion_authorized": True})
    except ValueError as exc:
        assert "internally inconsistent" in str(exc)
    else:
        raise AssertionError("conflicting terminal decision must fail closed")


def test_no_publication_is_terminal_and_preserves_production():
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        paths = fixture(root, {
            "population_id": POPULATION,
            "outcome": "NO_OP_NO_NEW_HANDS",
        })
        document, validation = finalize(root, paths)
        assert document["outcome"] == "NO_OP"
        assert document["state"] == "VERIFIED_NO_PUBLICATION"
        assert document["production_after"] == document["production_before"]
        assert document["deployment"] == {"attempted": False}
        assert validation["status"] == "PASS"
        assert validation["delivered"] is True


def test_promote_is_prepared_but_never_delivered_by_router():
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        paths = fixture(root, {
            "population_id": POPULATION,
            "outcome": "PROMOTE",
            "promotion_authorized": True,
        })
        candidate_release = root / "staging/RELEASE.json"
        candidate_registry = root / "staging/registry.json"
        candidate_pack = root / "staging/population-pack.zip"
        promotion_plan = root / "training/runs/cycle/PROMOTION_PLAN.json"
        write_json(candidate_release, {
            "schema": "poker-site-release/v3",
            "version": "candidate",
            "publication_verification": {"status": "UNVERIFIED_LIVE"},
        })
        write_json(candidate_registry, {"schema": "fixture-registry", "active": "candidate"})
        candidate_pack.parent.mkdir(parents=True, exist_ok=True)
        candidate_pack.write_bytes(b"candidate-pack")
        write_json(promotion_plan, {
            "schema": "poker-atomic-promotion/v1",
            "operations": [
                {
                    "id": "site-release",
                    "source": candidate_release.relative_to(root).as_posix(),
                    "destination": paths["release"].relative_to(root).as_posix(),
                    "source_sha256": sha256_file(candidate_release),
                    "destination_sha256_before": sha256_file(paths["release"]),
                },
                {
                    "id": "population-registry",
                    "source": candidate_registry.relative_to(root).as_posix(),
                    "destination": paths["registry"].relative_to(root).as_posix(),
                    "source_sha256": sha256_file(candidate_registry),
                    "destination_sha256_before": sha256_file(paths["registry"]),
                },
            ],
        })
        document, validation = finalize(
            root,
            paths,
            promotion_plan=promotion_plan,
            candidate_pack=candidate_pack,
            candidate_release=candidate_release,
            expected_commit="a" * 40,
            production_url="https://poker-engine.workers.dev",
        )
        assert document["outcome"] == "PROMOTE"
        assert document["state"] == "PREPARED"
        assert document["deployment"]["attempted"] is False
        assert validation["status"] == "PASS"
        assert validation["delivered"] is False


def test_promote_missing_publication_identity_fails_closed():
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        paths = fixture(root, {"outcome": "PROMOTE", "promotion_authorized": True})
        try:
            finalize(root, paths)
        except ValueError as exc:
            assert "PROMOTE requires --promotion-plan" in str(exc)
        else:
            raise AssertionError("PROMOTE without immutable publication inputs must fail")


def test_handoff_evidence_is_append_only():
    with tempfile.TemporaryDirectory() as raw:
        path = Path(raw) / "RELEASE_HANDOFF.json"
        write_new_handoff(path, {"schema": "fixture", "state": "first"})
        try:
            write_new_handoff(path, {"schema": "fixture", "state": "second"})
        except FileExistsError as exc:
            assert "refusing to overwrite" in str(exc)
        else:
            raise AssertionError("closed handoff evidence must never be overwritten")


def main():
    tests = [
        value
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    for fn in tests:
        fn()
    print(f"Finalize cycle release tests: {len(tests)} passed")


if __name__ == "__main__":
    main()

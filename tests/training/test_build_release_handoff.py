#!/usr/bin/env python3
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from tools.training.build_release_handoff import build_no_publication_handoff, derive_outcome


ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "training/automation/RELEASE_HANDOFF_CONTRACT.json"


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def fixture(tmp: Path, decision):
    decision_path=tmp/"run"/"DECISION.json"
    release=tmp/"site"/"RELEASE.json"
    registry=tmp/"training"/"populations"/"registry.json"
    snapshot=tmp/"snapshot.zip"
    write_json(decision_path, decision)
    write_json(release, {"release":"baseline"})
    write_json(registry, {"schema":"registry"})
    snapshot.write_bytes(b"immutable-snapshot")
    return decision_path,release,registry,snapshot


def build(tmp: Path, decision, *, outcome=None):
    decision_path,release,registry,snapshot=fixture(tmp, decision)
    return build_no_publication_handoff(
        root=tmp,
        population_id="population-a",
        cycle_run_id="cycle-1",
        cycle_decision_path=decision_path,
        snapshot=snapshot,
        snapshot_sha256=None,
        site_release_path=release,
        population_registry_path=registry,
        source_commit_sha="1"*40,
        outcome=outcome,
        reason="No production transition is authorized by this cycle.",
        contract_path=CONTRACT,
    )


def test_derives_no_op_from_increment_gate():
    assert derive_outcome({"status":"PASS","outcome":"NO_OP_NO_NEW_HANDS"})=="NO_OP"


def test_derives_blocked_and_retain_vocabularies():
    assert derive_outcome({"status":"PREPARED_BLOCKED"})=="BLOCKED"
    assert derive_outcome({"decision":"RETAIN_REFERENCE"})=="RETAIN"


def test_no_op_handoff_is_contract_valid_and_byte_identical_production():
    with tempfile.TemporaryDirectory() as raw:
        doc,validation=build(Path(raw), {"status":"PASS","outcome":"NO_OP_NO_NEW_HANDS","population_id":"population-a"})
    assert validation["status"]=="PASS" and validation["delivered"] is True
    assert doc["outcome"]=="NO_OP"
    assert doc["state"]=="VERIFIED_NO_PUBLICATION"
    assert doc["promotion_authorized"] is False
    assert doc["deployment"]=={"attempted":False}
    assert doc["production_after"]==doc["production_before"]


def test_explicit_outcome_cannot_conflict_with_decision():
    with tempfile.TemporaryDirectory() as raw:
        try:
            build(Path(raw), {"status":"BLOCKED","population_id":"population-a"}, outcome="RETAIN")
        except ValueError as exc:
            assert "conflicts" in str(exc)
        else:
            raise AssertionError("conflicting explicit outcome must fail")


def test_population_mismatch_fails_closed():
    with tempfile.TemporaryDirectory() as raw:
        try:
            build(Path(raw), {"status":"NO_OP","population_id":"other"})
        except ValueError as exc:
            assert "population mismatch" in str(exc)
        else:
            raise AssertionError("population mismatch must fail")


def main():
    tests=[value for name,value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for fn in tests:
        fn()
    print(f"Release handoff builder tests: {len(tests)} passed")


if __name__=="__main__":
    main()

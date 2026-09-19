#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.preflop.iso_sizing_posterior_binding import (
    IsoSizingPosteriorBindingError,
    reference_from_posterior_record,
    validate_diagnostics_posterior_bindings,
    validate_reference_against_record,
)
from src.ranges.posterior_range import (
    SCHEMA as POSTERIOR_SCHEMA,
    build_available_record,
    build_fail_closed_record,
    validate_posterior_range,
)

FIX = ROOT / "tests/fixtures/iso-sizing-diagnostics"


def load(name: str) -> dict:
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def build_records() -> dict[str, dict]:
    source = load("posterior_records_source.json")
    records = {}
    for ref_id, args in source["records"].items():
        records[ref_id] = build_available_record(**args)
        assert validate_posterior_range(records[ref_id]) == []
        assert records[ref_id]["schema"] == POSTERIOR_SCHEMA
    return records


def build_diagnostics() -> dict:
    # Use the shipped #322 bridge rather than manufacturing a diagnostics artifact in Python.
    script = r"""
const fs=require('node:fs');
const path=require('node:path');
const D=require('./src/preflop/iso-sizing-diagnostics.js');
const fix=path.resolve('tests/fixtures/iso-sizing-diagnostics');
const read=n=>JSON.parse(fs.readFileSync(path.join(fix,n),'utf8'));
process.stdout.write(JSON.stringify(D.bridgePairedResult({
  decision:read('canonical_decision.json'),
  paired_result:read('paired_result.json'),
  diagnostic_worlds:read('diagnostic_worlds.json')
})));
"""
    raw = subprocess.check_output(["node", "-e", script], cwd=ROOT, text=True)
    return json.loads(raw)


def expect_binding_error(fn, contains: str) -> None:
    try:
        fn()
    except IsoSizingPosteriorBindingError as exc:
        assert contains in str(exc), str(exc)
    else:
        raise AssertionError(f"expected binding failure containing {contains!r}")


def test_final_320_records_match_every_322_reference() -> None:
    diagnostics = build_diagnostics()
    records = build_records()
    report = validate_diagnostics_posterior_bindings(diagnostics, records)
    assert report["posterior_schema"] == "poker-opponent-posterior-range/v1"
    assert report["validated_references"] > 0
    assert report["unique_records"] == 12
    assert report["selection_effect"] == "NONE_EXPLANATORY_ONLY"


def test_fixture_links_iso_4_5_6_to_valid_final_records() -> None:
    diagnostics = build_diagnostics()
    records = build_records()
    alternatives = {row["alternative_id"]: row for row in diagnostics["alternatives"]}
    for alt_id in ("ISO@4", "ISO@5", "ISO@6"):
        refs = alternatives[alt_id]["posterior_refs"]
        assert refs
        for entry in refs:
            ref = entry["ref"]
            assert ref["schema"] == POSTERIOR_SCHEMA
            record = records[ref["ref_id"]]
            assert reference_from_posterior_record(ref["ref_id"], record) == ref


def test_identity_fingerprint_moment_status_fail_closed() -> None:
    diagnostics = build_diagnostics()
    records = build_records()
    sample = next(
        entry["ref"]
        for row in diagnostics["alternatives"]
        if row["alternative_id"] == "ISO@5"
        for entry in row["posterior_refs"]
    )
    record = records[sample["ref_id"]]

    bad = copy.deepcopy(sample)
    bad["identity"]["model_version"] = "wrong"
    expect_binding_error(lambda: validate_reference_against_record(bad, record), "identity")

    bad = copy.deepcopy(sample)
    bad["distribution_fingerprint"] = "sha256:" + "0" * 64
    expect_binding_error(lambda: validate_reference_against_record(bad, record), "distribution_fingerprint")

    before = build_available_record(
        **{
            **load("posterior_records_source.json")["records"][sample["ref_id"]],
            "moment": "BEFORE_ACTION",
            "public_action": None,
        }
    )
    expect_binding_error(
        lambda: validate_reference_against_record(sample, before, expected_position=sample["position"], expected_response=sample["public_action"]["action"]),
        "moment",
    )

    source = load("posterior_records_source.json")["records"][sample["ref_id"]]
    unsupported = build_fail_closed_record(
        status="UNSUPPORTED",
        reason="synthetic unsupported",
        hand_id=source["hand_id"],
        step_id=source["step_id"],
        public_state_fingerprint=source["public_state_fingerprint"],
        player=source["player"],
        position=source["position"],
        identity=source["identity"],
        moment=source["moment"],
        public_action=source["public_action"],
        blockers_applied=source["blockers_applied"],
        source_observations=0,
        backoff_level="UNSUPPORTED",
        backoff_reason="synthetic",
        provenance=source["provenance"],
    )
    expect_binding_error(lambda: validate_reference_against_record(sample, unsupported), "status")


def test_invalid_320_record_is_rejected_by_reused_validator() -> None:
    records = build_records()
    record = copy.deepcopy(next(iter(records.values())))
    record["distribution_fingerprint"] = "sha256:" + "f" * 64
    expect_binding_error(
        lambda: reference_from_posterior_record("tampered", record),
        "distribution_fingerprint mismatch",
    )


def test_fail_closed_320_statuses_are_projectable_without_fake_hash() -> None:
    source = next(iter(load("posterior_records_source.json")["records"].values()))
    for status in ("UNSUPPORTED", "INVALID"):
        record = build_fail_closed_record(
            status=status,
            reason="synthetic fail closed",
            hand_id=source["hand_id"],
            step_id=source["step_id"],
            public_state_fingerprint=source["public_state_fingerprint"],
            player=source["player"],
            position=source["position"],
            identity=source["identity"],
            moment=source["moment"],
            public_action=source["public_action"],
            blockers_applied=source["blockers_applied"],
            source_observations=0,
            backoff_level="UNSUPPORTED",
            backoff_reason="synthetic",
            provenance=source["provenance"],
        )
        ref = reference_from_posterior_record("fail-closed", record)
        assert ref["status"] == status
        assert ref["distribution_fingerprint"] is None


def test_resolver_selection_is_unchanged_by_final_posterior_binding() -> None:
    diagnostics = build_diagnostics()
    records = build_records()
    validate_diagnostics_posterior_bindings(diagnostics, records)
    decision = load("canonical_decision.json")
    # The JS contract's canonical max-EV selection remains ISO@5.
    assert decision["selected_id"] == "ISO@5"
    iso6 = next(row for row in diagnostics["alternatives"] if row["alternative_id"] == "ISO@6")
    iso5 = next(row for row in diagnostics["alternatives"] if row["alternative_id"] == "ISO@5")
    assert iso6["expected_callers"] < iso5["expected_callers"]


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
    print(f"iso-sizing posterior #320 binding tests: {len(tests)} passed")

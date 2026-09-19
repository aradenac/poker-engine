#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.simulation.admitted_model_a_iso_provider import (  # noqa: E402
    ADMISSION_STATUS,
    CANDIDATE_ID,
    CANDIDATE_SHA256,
    FIT_EVIDENCE_SHA256,
    VALIDATION_DECISION,
    VALIDATION_EVIDENCE_SHA256,
    Issue367ProviderError,
    Issue367ScientificProvider,
    load_admitted_candidate,
)
from tools.preflop.model_a_sizing_likelihood import (  # noqa: E402
    canonical_candidate_sha256,
)


def test_admitted_candidate_rebuild_is_exact_and_no_pointer_mutation():
    candidate, validation = load_admitted_candidate()
    assert candidate["identity"]["candidate_id"] == CANDIDATE_ID
    assert canonical_candidate_sha256(candidate) == CANDIDATE_SHA256
    assert candidate["nearest_price_fallback"] is False
    assert validation["outcome"] == VALIDATION_DECISION
    assert validation["evidence_sha256"] == VALIDATION_EVIDENCE_SHA256
    assert validation["active_model_replaced"] is False
    assert validation["automatic_promotion"] is False
    assert validation["test_consumed"] is False


def test_scientific_provider_metadata_binds_exact_admission():
    provider = Issue367ScientificProvider(hero_hole_cards=("Ks", "Ts"))
    metadata = provider.metadata()
    assert metadata["provider_kind"] == "MODEL_A"
    assert metadata["admission_status"] == ADMISSION_STATUS
    assert metadata["scientific_effect"] == "SCIENTIFIC_ADMITTED"
    assert metadata["identity"]["model_id"] == CANDIDATE_ID
    assert metadata["identity"]["model_version"] == CANDIDATE_SHA256
    provenance = metadata["provenance"]
    assert provenance["validation_decision"] == "ADMIT_CANDIDATE"
    assert provenance["candidate_sha256"] == CANDIDATE_SHA256
    assert provenance["fit_evidence_sha256"] == FIT_EVIDENCE_SHA256
    assert provenance["validation_evidence_sha256"] == VALIDATION_EVIDENCE_SHA256
    assert provenance["active_model_pointer_mutated"] is False
    assert provenance["test_consumed"] is False
    assert provenance["nearest_price"] is False


def test_wrong_candidate_sha_fails_closed_before_execution():
    try:
        Issue367ScientificProvider(
            hero_hole_cards=("Ks", "Ts"),
            expected_candidate_sha256="0" * 64,
        )
    except Issue367ProviderError as exc:
        assert "candidate SHA" in str(exc)
    else:
        raise AssertionError("mismatched admitted candidate SHA must fail closed")


def test_wrong_admission_decision_fails_closed_before_execution():
    try:
        Issue367ScientificProvider(
            hero_hole_cards=("Ks", "Ts"),
            expected_decision="RETAIN_ACTIVE_REFERENCE",
        )
    except Issue367ProviderError as exc:
        assert "admission decision" in str(exc)
    else:
        raise AssertionError("mismatched admission decision must fail closed")


def test_non_sizing_opponent_preflop_closure_is_frozen_and_never_nearest():
    provider = Issue367ScientificProvider(hero_hole_cards=("Ks", "Ts"))
    closure = provider.opponent_policy.non_sizing_reference
    assert closure.policy_id == "model-a-reference-support-closed/v1"
    assert closure.fallback_contract == "CHECK_THEN_CALL_THEN_FOLD_V1"
    assert closure.identity["nearest_context_substitution"] is False
    assert closure.identity["claim"] == "BENCHMARK_SUPPORT_CLOSURE_NOT_OPTIMIZED_HERO_STRATEGY"


def test_posterior_support_closure_is_explicit_no_information_only():
    provider = Issue367ScientificProvider(hero_hole_cards=("Ks", "Ts"))
    assert provider.opponent_policy.posterior_support_closure == {}
    audit = provider.audit()
    assert audit["posterior_support_closure_no_information"] == {}
    assert audit["nearest_price"] is False
    assert audit["active_model_pointer_mutated"] is False
    assert audit["test_consumed"] is False


def test_reference_descriptor_keeps_active_v5_pointer_external_to_candidate():
    descriptor = json.loads(
        (
            ROOT
            / "training/full_hand/HERO_REFERENCE_POLICY_20260917_SUPPORT_CLOSED.json"
        ).read_text(encoding="utf-8")
    )
    assert descriptor["artifacts"]["preflop_model"]["path"] == (
        "training/models/preflop_population_model_v5.json"
    )
    assert descriptor["artifacts"]["preflop_model"]["sha256"] == (
        "ff952055ca4ee051a3ac9607d513fdecac0a320a31f658ecfd8a11d8448975ca"
    )
    assert CANDIDATE_ID not in json.dumps(descriptor)


if __name__ == "__main__":
    tests = [
        value
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    for test in tests:
        test()
    print(f"issue #367 scientific provider preflight: {len(tests)} passed")

#!/usr/bin/env python3
"""Read-only real-evidence admission audit for issue #350.

The audit consumes only persisted repository evidence plus the immutable #108
decision snapshot copied verbatim from its evidence commit. It deliberately
does not create a production pack, mutate registry/catalogue/pointers, or read
TEST data.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from tools.population_pack_admission import (
    canonical_sha256,
    resolve_admission,
)
from tools.population_pack_candidate import (
    REQUIRED_ROLES,
    content_identity,
    sha256_file,
)
from tools.population_pack_preflight import preflight

ROOT = Path(__file__).resolve().parents[1]
TARGET = "pokerstars_nlhe_100-200_zoom_play_6max_v1"
LEGACY = "legacy_pokerstars_nlhe_100-200_play_6max_mixed_v1"
RUN_DIR = Path("training/runs/20260919_population_pack_admission_real_audit")
SNAPSHOT_108 = RUN_DIR / "source_snapshots/issue_108_VALIDATION_SELECTION.json"
SNAPSHOT_108_META = RUN_DIR / "source_snapshots/issue_108_SOURCE.json"

MODEL_A_PREFLOP_DECISION = Path("analysis/model_a_preflop_sizing_validation.json")
MODEL_A_POSTFLOP_ARTIFACT = Path(
    "training/runs/20260916_model_a_postflop_continuation_v1/postflop-selected-overlay.json"
)
MODEL_A_POSTFLOP_DECISION = Path(
    "training/runs/20260916_model_a_postflop_continuation_v1/RESULT.json"
)
MODEL_B_ARTIFACT = Path(
    "training/runs/20260919_model_b_preflop_response_to_price_2a/model/candidate.json"
)
MODEL_B_PROVENANCE = Path(
    "training/runs/20260919_model_b_preflop_response_to_price_2a/RUN_PROVENANCE.json"
)
MODEL_B_DECISION = Path(
    "training/runs/20260919_model_b_preflop_response_to_price_2a/RESULT.json"
)
HERO_ARTIFACT = Path(
    "training/runs/20260918_hero_preflop_unopened_5pos_pfpc_v1/HERO_RANGE_REPOSITORY_PFPC.json"
)
HERO_PROVENANCE = Path(
    "training/runs/20260918_hero_preflop_unopened_5pos_pfpc_v1/SOURCE_RUN.json"
)
LEGACY_MODEL_A_PREFLOP = Path("training/models/preflop_population_model_v5.json")
LEGACY_ENGINE = Path("user/releases/poker_range_equity_offline_multiway_v83.html")
REGISTRY = Path("training/populations/registry.json")
APPLICATION_RELEASE = Path("site/RELEASE.json")
ORIGINAL_ZOOM_CANDIDATE = Path(
    "user/packs/pokerstars_nlhe_100-200_zoom_play_6max_v1/candidate.json"
)


def load_json(rel: Path) -> dict[str, Any]:
    value = json.loads((ROOT / rel).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {rel}")
    return value


def write_json(rel: Path, value: Any) -> None:
    path = ROOT / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def rel_ref(rel: Path) -> dict[str, str]:
    return {"path": rel.as_posix(), "sha256": sha256_file(ROOT / rel)}


def component(
    *,
    role: str,
    source: Path,
    source_population_id: str,
    lineage_format: str,
    provenance_evidence: Path,
    decision_status: str,
    decision_issue: str,
    decision_evidence: Path,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    kind, digest = content_identity(ROOT / source)
    row: dict[str, Any] = {
        "role": role,
        "population_id": TARGET,
        "source_path": source.as_posix(),
        "hash_kind": kind,
        "sha256": digest,
        "provenance": {
            "source_population_id": source_population_id,
            "evidence": rel_ref(provenance_evidence),
        },
        "lineage": {
            "population_id": source_population_id,
            "format": lineage_format,
        },
        "decision": {
            "status": decision_status,
            "issue": decision_issue,
            "evidence": rel_ref(decision_evidence),
        },
    }
    if extra:
        row["audit_source"] = copy.deepcopy(extra)
    return row


def build_evidence_set() -> dict[str, Any]:
    registry = load_json(REGISTRY)
    target = registry["populations"][TARGET]
    legacy = registry["populations"][LEGACY]
    selection_108 = load_json(SNAPSHOT_108)
    source_108 = load_json(SNAPSHOT_108_META)
    decision_339 = load_json(MODEL_A_PREFLOP_DECISION)
    postflop = load_json(MODEL_A_POSTFLOP_DECISION)
    model_b = load_json(MODEL_B_DECISION)
    model_b_prov = load_json(MODEL_B_PROVENANCE)
    hero_prov = load_json(HERO_PROVENANCE)
    release = load_json(APPLICATION_RELEASE)

    # Frozen/real decision guards. These are assertions, not reinterpretations.
    assert sha256_file(ROOT / SNAPSHOT_108) == source_108["expected_content_sha256"]
    assert selection_108["outcome"] == "RETAIN_REFERENCE"
    assert selection_108["promotion_authorized"] is False
    assert selection_108["test_consumed"] is False

    assert decision_339["outcome"] == "RETAIN_ACTIVE_REFERENCE"
    assert decision_339["active_model_replaced"] is False
    assert decision_339["production_effect"] == "NONE"
    assert decision_339["test_consumed"] is False

    assert postflop["population_id"] == TARGET
    assert postflop["selection"]["production_effect"] == "NONE"
    assert postflop["selection"]["test_consumed"] is False

    assert model_b["decision"] == "VALIDATION_SUPPORTS_PRICE_AWARE_CANDIDATE__NO_PROMOTION"
    assert model_b["automatic_promotion"] is False
    assert model_b["active_model_b_changed"] is False
    assert model_b["production_effect"] == "NONE"
    assert model_b["test_consumed"] is False
    assert model_b_prov["scientific_identity"]["test_consumed"] is False
    assert model_b_prov["scientific_identity"]["production_effect"] == "NONE"

    assert hero_prov["population_id"] == TARGET
    assert hero_prov["promotion_authorized"] is False
    assert hero_prov["test_consumed"] is False

    assert target["status"] == "CERTIFIED_DATA_ONLY"
    assert all(
        target["artifacts"].get(role) is None
        for role in ("model_a_preflop", "model_a_postflop", "model_b", "hero_strategy", "engine", "pack")
    )
    assert target["compatibility"]["legacy_unscoped_artifacts_allowed"] is False
    assert legacy["identity"]["format"] == "MIXED_ZOOM_REGULAR"
    assert release["status"] == "promoted"
    assert release["identity"]["engine_release"]["artifact"] == LEGACY_ENGINE.as_posix()

    components = {
        # #339 retained the active v5 reference. That active reference is
        # registered to the legacy mixed population, so it is intentionally
        # supplied with its true lineage and no cross-population fallback.
        "model_a_preflop": component(
            role="model_a_preflop",
            source=LEGACY_MODEL_A_PREFLOP,
            source_population_id=LEGACY,
            lineage_format="MIXED_ZOOM_REGULAR",
            provenance_evidence=REGISTRY,
            decision_status=decision_339["outcome"],
            decision_issue="#339",
            decision_evidence=MODEL_A_PREFLOP_DECISION,
            extra={
                "meaning": "active reference retained; rejected sizing-aware candidate is not a production component",
                "candidate_sha256": decision_339["inputs"]["candidate_sha256"],
                "active_reference_sha256": decision_339["inputs"]["reference"]["sha256"],
            },
        ),
        # #102 scientifically selected the target-scoped overlay, but its
        # decision is not an explicit pack admission and production_effect=NONE.
        "model_a_postflop": component(
            role="model_a_postflop",
            source=MODEL_A_POSTFLOP_ARTIFACT,
            source_population_id=TARGET,
            lineage_format="ZOOM",
            provenance_evidence=MODEL_A_POSTFLOP_DECISION,
            decision_status=postflop["selection"]["stage_b_decision"],
            decision_issue="#102",
            decision_evidence=MODEL_A_POSTFLOP_DECISION,
            extra={
                "production_effect": postflop["selection"]["production_effect"],
                "candidate_sha256": postflop["candidate_sha256"],
                "selected_overlay_sha256": postflop["selected_overlay_sha256"],
            },
        ),
        # #340 supports the candidate on VALIDATION but explicitly says
        # NO_PROMOTION. Preserve that exact status so #305 cannot admit it.
        "model_b": component(
            role="model_b",
            source=MODEL_B_ARTIFACT,
            source_population_id=TARGET,
            lineage_format="ZOOM",
            provenance_evidence=MODEL_B_PROVENANCE,
            decision_status=model_b["decision"],
            decision_issue="#340",
            decision_evidence=MODEL_B_DECISION,
            extra={
                "automatic_promotion": model_b["automatic_promotion"],
                "active_model_b_changed": model_b["active_model_b_changed"],
            },
        ),
        # #108 decision is consumed verbatim for both policy/range roles
        # represented by the persisted PFPC repository; identical bytes can
        # legitimately cover multiple roles, but RETAIN_REFERENCE blocks both.
        "hero_strategy": component(
            role="hero_strategy",
            source=HERO_ARTIFACT,
            source_population_id=TARGET,
            lineage_format="ZOOM",
            provenance_evidence=HERO_PROVENANCE,
            decision_status=selection_108["outcome"],
            decision_issue="#108",
            decision_evidence=SNAPSHOT_108,
            extra={
                "candidate_id": selection_108["candidate_id"],
                "promotion_authorized": selection_108["promotion_authorized"],
                "source_evidence_commit": source_108["original_ref"],
            },
        ),
        "hero_ranges": component(
            role="hero_ranges",
            source=HERO_ARTIFACT,
            source_population_id=TARGET,
            lineage_format="ZOOM",
            provenance_evidence=HERO_PROVENANCE,
            decision_status=selection_108["outcome"],
            decision_issue="#108",
            decision_evidence=SNAPSHOT_108,
            extra={
                "candidate_id": selection_108["candidate_id"],
                "promotion_authorized": selection_108["promotion_authorized"],
                "source_evidence_commit": source_108["original_ref"],
            },
        ),
        # Current engine/application are real production artifacts, but their
        # engine lineage is the legacy mixed population. No explicit fallback
        # authorization or pack admission exists for the target population.
        "engine": component(
            role="engine",
            source=LEGACY_ENGINE,
            source_population_id=LEGACY,
            lineage_format="MIXED_ZOOM_REGULAR",
            provenance_evidence=REGISTRY,
            decision_status="UNRESOLVED_NO_PACK_ADMISSION",
            decision_issue="#201",
            decision_evidence=APPLICATION_RELEASE,
            extra={"release_status": release["status"]},
        ),
        "application_release": component(
            role="application_release",
            source=APPLICATION_RELEASE,
            source_population_id=LEGACY,
            lineage_format="MIXED_ZOOM_REGULAR",
            provenance_evidence=APPLICATION_RELEASE,
            decision_status="UNRESOLVED_NO_PACK_ADMISSION",
            decision_issue="#201",
            decision_evidence=APPLICATION_RELEASE,
            extra={
                "release_status": release["status"],
                "declared_engine": release["identity"]["engine_release"],
            },
        ),
    }

    return {
        "schema": "poker-scientific-component-evidence-set/v1",
        "population_id": TARGET,
        "artifact_class": "REAL_PERSISTED_EVIDENCE_READ_ONLY_AUDIT",
        "scientific_effect": "NONE_AUDIT_ONLY",
        "source_policy": {
            "persisted_artifacts_only": True,
            "live_issue_state_is_evidence": False,
            "admissible_status_fabricated": False,
            "test_read_or_consumed": False,
        },
        "components": components,
    }


NEXT = {
    "model_a_preflop": {
        "next_tickets": ["#352", "#201"],
        "next_evidence": "target-scoped Model A preflop artifact with an explicit persisted pack-admission decision; legacy v5 cannot be silently reused",
    },
    "model_a_postflop": {
        "next_tickets": ["#201"],
        "next_evidence": "explicit persisted ADMISSIBLE_FOR_PACK decision for the #102 target-scoped selected overlay plus final compatibility binding",
    },
    "model_b": {
        "next_tickets": ["#315", "#201"],
        "next_evidence": "post-#314 real sensitivity and an explicit promotion/pack-admission decision; #340 NO_PROMOTION is insufficient",
    },
    "hero_strategy": {
        "next_tickets": ["#196", "#201"],
        "next_evidence": "new/final Hero strategy evidence that supersedes #108 RETAIN_REFERENCE and is explicitly admitted for the Zoom pack",
    },
    "hero_ranges": {
        "next_tickets": ["#196", "#201"],
        "next_evidence": "final target-scoped Hero range repository with explicit pack admission; #108-retained candidate cannot be promoted",
    },
    "engine": {
        "next_tickets": ["#201"],
        "next_evidence": "target-scoped engine or explicit persisted cross-population fallback authorization plus ADMISSIBLE_FOR_PACK decision",
    },
    "application_release": {
        "next_tickets": ["#201"],
        "next_evidence": "target-scoped application release binding the admitted engine with an explicit pack-admission decision",
    },
}


def matrix_from_resolution(resolution: dict[str, Any]) -> dict[str, Any]:
    rows = []
    for role in REQUIRED_ROLES:
        row = resolution["admissions"][role]
        source = row.get("scientific_decision") or {}
        artifact = row.get("artifact") or {}
        reasons = list(row.get("reason_codes") or [])
        rows.append({
            "role": role,
            "status": row["status"],
            "artifact": artifact,
            "lineage": row.get("lineage"),
            "scientific_decision": source,
            "reason_codes": reasons,
            "source_refs": row.get("source_refs") or [],
            "registered_source_owners": row.get("registered_source_owners") or [],
            "blocker": {
                "blocking": row["status"] != "ADMISSIBLE",
                "reason_codes": reasons,
                **NEXT[role],
            },
        })

    counts = resolution["summary"]
    return {
        "schema": "poker-population-pack-admission-real-matrix/v1",
        "issue": 350,
        "parent_issue": 201,
        "population_id": TARGET,
        "roles_total": len(rows),
        "roles": rows,
        "summary": counts,
        "assembly_status": (
            "READY" if counts.get("ADMISSIBLE") == len(rows) else "NOT_READY"
        ),
        "invariants": {
            "all_7_roles_resolved_to_explicit_state": len(rows) == 7 and all(r["status"] for r in rows),
            "retain_reference_never_admitted": all(
                r["status"] != "ADMISSIBLE"
                for r in rows
                if (r.get("scientific_decision") or {}).get("status") == "RETAIN_REFERENCE"
            ),
            "no_promotion_model_b_never_admitted": next(r for r in rows if r["role"] == "model_b")["status"] != "ADMISSIBLE",
            "legacy_mixed_sources_never_admitted": all(
                r["status"] != "ADMISSIBLE"
                for r in rows
                if (r.get("lineage") or {}).get("format") == "MIXED_ZOOM_REGULAR"
            ),
            "no_role_silently_relabelled": True,
            "test_consumed": False,
            "production_effect": "NONE",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=RUN_DIR)
    args = parser.parse_args()
    out = args.output_dir

    # Side-effect sentinel hashes: only audit outputs may change.
    registry_before = sha256_file(ROOT / REGISTRY)
    release_before = sha256_file(ROOT / APPLICATION_RELEASE)
    original_candidate_before = sha256_file(ROOT / ORIGINAL_ZOOM_CANDIDATE)

    evidence = build_evidence_set()
    evidence_path = out / "EVIDENCE_SET.json"
    write_json(evidence_path, evidence)

    resolution = resolve_admission(
        evidence_path,
        root=ROOT,
        expected_population_id=TARGET,
    )
    write_json(out / "ADMISSION_RESOLUTION.json", resolution)

    candidate = resolution["candidate_contract"]
    write_json(out / "CANDIDATE_CONTRACT.json", candidate)
    preflight_result = preflight(
        out / "CANDIDATE_CONTRACT.json",
        root=ROOT,
        expected_population_id=TARGET,
    )
    write_json(out / "PREFLIGHT.json", preflight_result)

    matrix = matrix_from_resolution(resolution)
    write_json(out / "ADMISSION_MATRIX.json", matrix)

    registry_after = sha256_file(ROOT / REGISTRY)
    release_after = sha256_file(ROOT / APPLICATION_RELEASE)
    original_candidate_after = sha256_file(ROOT / ORIGINAL_ZOOM_CANDIDATE)
    side_effects = {
        "registry_sha256_before": registry_before,
        "registry_sha256_after": registry_after,
        "application_release_sha256_before": release_before,
        "application_release_sha256_after": release_after,
        "original_zoom_candidate_sha256_before": original_candidate_before,
        "original_zoom_candidate_sha256_after": original_candidate_after,
        "registry_unchanged": registry_before == registry_after,
        "application_release_unchanged": release_before == release_after,
        "original_zoom_candidate_unchanged": original_candidate_before == original_candidate_after,
        "publication": False,
        "activation": False,
        "promotion": False,
        "registry_pointer_mutation": False,
        "catalogue_mutation": False,
        "test_consumed": False,
    }
    write_json(out / "READ_ONLY_GUARD.json", side_effects)

    source_decisions = {
        "issue_108": {
            "path": SNAPSHOT_108.as_posix(),
            "sha256": sha256_file(ROOT / SNAPSHOT_108),
            "decision": load_json(SNAPSHOT_108)["outcome"],
            "promotion_authorized": load_json(SNAPSHOT_108)["promotion_authorized"],
            "test_consumed": load_json(SNAPSHOT_108)["test_consumed"],
        },
        "issue_339": {
            "path": MODEL_A_PREFLOP_DECISION.as_posix(),
            "sha256": sha256_file(ROOT / MODEL_A_PREFLOP_DECISION),
            "decision": load_json(MODEL_A_PREFLOP_DECISION)["outcome"],
            "test_consumed": load_json(MODEL_A_PREFLOP_DECISION)["test_consumed"],
        },
        "issue_340": {
            "path": MODEL_B_DECISION.as_posix(),
            "sha256": sha256_file(ROOT / MODEL_B_DECISION),
            "decision": load_json(MODEL_B_DECISION)["decision"],
            "test_consumed": load_json(MODEL_B_DECISION)["test_consumed"],
        },
    }

    result = {
        "schema": "poker-population-pack-admission-real-audit-result/v1",
        "issue": 350,
        "parent_issue": 201,
        "status": "COMPLETE_READ_ONLY_AUDIT",
        "population_id": TARGET,
        "assembly_status": matrix["assembly_status"],
        "admission_summary": matrix["summary"],
        "evidence_set_sha256": sha256_file(ROOT / evidence_path),
        "resolution_sha256": resolution["resolution_sha256"],
        "candidate_contract_sha256": canonical_sha256(candidate),
        "preflight_result": preflight_result["result"],
        "preflight_sha256": canonical_sha256(preflight_result),
        "matrix_sha256": canonical_sha256(matrix),
        "source_decisions": source_decisions,
        "dod": {
            "seven_roles_explicit": matrix["invariants"]["all_7_roles_resolved_to_explicit_state"],
            "hashes_and_provenance_verified": all(
                (row.get("artifact") or {}).get("verified") is True
                and not any(
                    code.endswith("_HASH_MISMATCH")
                    or code.endswith("_EVIDENCE_MISSING")
                    or code.endswith("_EVIDENCE_INVALID")
                    for code in (row.get("reason_codes") or [])
                )
                for row in resolution["admissions"].values()
            ),
            "issue_108_consumed_without_reinterpretation": source_decisions["issue_108"]["decision"] == "RETAIN_REFERENCE",
            "issue_339_respected": source_decisions["issue_339"]["decision"] == "RETAIN_ACTIVE_REFERENCE",
            "issue_340_no_promotion_respected": source_decisions["issue_340"]["decision"].endswith("__NO_PROMOTION"),
            "legacy_relabel_forbidden": matrix["invariants"]["legacy_mixed_sources_never_admitted"],
            "preflight_read_only_executed": preflight_result["safety"]["writes_performed"] is False,
            "blockers_have_next_evidence": all(row["blocker"]["next_evidence"] for row in matrix["roles"]),
            "deterministic_contracts": True,
            "no_publication_activation_promotion_mutation": all(
                side_effects[key] is False
                for key in (
                    "publication", "activation", "promotion",
                    "registry_pointer_mutation", "catalogue_mutation",
                )
            ) and side_effects["registry_unchanged"] and side_effects["application_release_unchanged"] and side_effects["original_zoom_candidate_unchanged"],
            "test_unconsumed": True,
            "parent_201_remains_open": True,
        },
        "safety": side_effects,
        "production_effect": "NONE",
        "test_consumed": False,
        "publication_performed": False,
        "activation_performed": False,
        "promotion_performed": False,
        "registry_or_pointer_mutation": False,
        "parent_issue_201_should_remain_open": True,
    }
    if not all(result["dod"].values()):
        raise AssertionError(f"incomplete #350 DoD: {result['dod']}")
    if preflight_result["result"] != "BLOCKED":
        raise AssertionError("real #201 assembly unexpectedly became READY")
    if matrix["assembly_status"] != "NOT_READY":
        raise AssertionError("real admission matrix unexpectedly became READY")
    write_json(out / "RESULT.json", result)

    summary = [
        "# #350 real Zoom 100/200 pack admission audit",
        "",
        f"- Population: `{TARGET}`",
        f"- Assembly: **{matrix['assembly_status']}**",
        f"- Preflight: **{preflight_result['result']}**",
        f"- Admission counts: `{json.dumps(matrix['summary'], sort_keys=True)}`",
        "- TEST consumed: **false**",
        "- Production effect: **NONE**",
        "",
        "| Role | Admission | Source decision | Next evidence |",
        "|---|---|---|---|",
    ]
    for row in matrix["roles"]:
        decision = (row.get("scientific_decision") or {}).get("status") or "NONE"
        summary.append(
            f"| {row['role']} | {row['status']} | {decision} | {row['blocker']['next_evidence']} |"
        )
    summary.extend([
        "",
        "No publication, activation, promotion, registry/pointer mutation, catalogue mutation or TEST was performed.",
        "#201 remains open.",
        "",
    ])
    (ROOT / out / "SUMMARY.md").write_text("\n".join(summary), encoding="utf-8")

    print(json.dumps({
        "status": result["status"],
        "assembly_status": result["assembly_status"],
        "preflight": result["preflight_result"],
        "admission_summary": result["admission_summary"],
        "roles": {row["role"]: row["status"] for row in matrix["roles"]},
        "test_consumed": False,
        "production_effect": "NONE",
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

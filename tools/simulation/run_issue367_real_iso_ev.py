#!/usr/bin/env python3
"""Execute the frozen real #314/#367 canonical ISO decision.

This command is intentionally unusable before PROTOCOL.json is frozen. It reads
no protected poker TEST split and does not promote/mutate any active model.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.simulation.admitted_model_a_iso_provider import (  # noqa: E402
    ADMISSION_STATUS,
    CANDIDATE_ID,
    CANDIDATE_SHA256,
    FIT_EVIDENCE_SHA256,
    VALIDATION_DECISION,
    VALIDATION_EVIDENCE_SHA256,
    Issue367ScientificProvider,
)
from tools.simulation.hero_preflop_iso_runner import run_hero_preflop_iso  # noqa: E402
from tools.simulation.paired_adaptive_preflop_ev import AdaptiveBudget  # noqa: E402

DEFAULT_PROTOCOL = (
    ROOT / "training/runs/20260919_issue367_real_iso_ev_v1/PROTOCOL.json"
)
SUPPORT = ROOT / "analysis/preflop_sizing_support_train.json"
FIXTURE = (
    ROOT
    / "tests/fixtures/repro/kts_sb_two_limp_iso4_three_calls.snapshots.json"
)


def _load(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _canonical_sha(value: Any) -> str:
    raw = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def load_protocol(path: Path) -> dict[str, Any]:
    protocol = _load(path)
    if protocol.get("schema") != "poker-issue367-real-iso-ev-protocol/v1":
        raise ValueError("unexpected #367 protocol schema")
    if protocol.get("status") != "FROZEN_BEFORE_REAL_EXECUTION":
        raise ValueError("#367 protocol must be frozen before execution")
    model = protocol.get("model_a") or {}
    if model.get("candidate_id") != CANDIDATE_ID:
        raise ValueError("frozen candidate id mismatch")
    if model.get("candidate_sha256") != CANDIDATE_SHA256:
        raise ValueError("frozen candidate SHA mismatch")
    if model.get("admission_decision") != VALIDATION_DECISION:
        raise ValueError("frozen admission decision mismatch")
    if model.get("fit_evidence_sha256") != FIT_EVIDENCE_SHA256:
        raise ValueError("frozen fit evidence mismatch")
    if model.get("validation_evidence_sha256") != VALIDATION_EVIDENCE_SHA256:
        raise ValueError("frozen validation evidence mismatch")
    if model.get("active_model_pointer_mutation") is not False:
        raise ValueError("active Model A pointer mutation is forbidden")

    science = protocol.get("scientific_boundary") or {}
    if science.get("test_consumed") is not False:
        raise ValueError("TEST must remain unconsumed")
    if science.get("model_b_consumed") is not False:
        raise ValueError("Model B is forbidden in #367")
    if science.get("promotion_performed") is not False:
        raise ValueError("promotion is forbidden in #367")

    grid = protocol.get("exact_support_grid") or {}
    requested = [float(x) for x in grid.get("requested_targets_bb") or []]
    supported = [float(x) for x in grid.get("scientific_supported_targets_bb") or []]
    if requested != [4.0, 5.0, 6.0]:
        raise ValueError("canonical requested ISO grid must stay frozen at 4/5/6 BB")
    if supported != [5.0]:
        raise ValueError(
            "#352 canonical exact response support admits only 5 BB for this real slice"
        )
    if grid.get("nearest_price") is not False:
        raise ValueError("nearest-price is forbidden")

    selection = protocol.get("selection") or {}
    if selection.get("rule") != "MAX_EV_POINT_ESTIMATE_ONLY":
        raise ValueError("recommendation rule must be max-EV only")
    if selection.get("indifference_rule") != "PAIRED_CI95_INCLUDES_ZERO":
        raise ValueError("unexpected frozen indifference rule")
    return protocol


def canonical_state() -> tuple[dict[str, Any], str]:
    fixture = _load(FIXTURE)
    if fixture.get("fixture_id") != "kts_sb_two_limp_iso4_three_calls_v1":
        raise ValueError("unexpected #321 fixture")
    row = next(
        item for item in fixture["snapshots"] if item["id"] == "before_hero"
    )
    state = copy.deepcopy(row["state"])
    # #321 snapshots are deliberately public-state snapshots. Rehydrate the
    # public action history needed by Model A from the canonical scenario.
    state["action_log"] = [
        {
            "street": "preflop",
            "player": "UTG",
            "action": "FOLD",
            "target_total_bb": None,
            "incremental_cost_bb": 0,
        },
        {
            "street": "preflop",
            "player": "HJ",
            "action": "FOLD",
            "target_total_bb": None,
            "incremental_cost_bb": 0,
        },
        {
            "street": "preflop",
            "player": "CO",
            "action": "CALL",
            "target_total_bb": None,
            "incremental_cost_bb": 1,
        },
        {
            "street": "preflop",
            "player": "BTN",
            "action": "CALL",
            "target_total_bb": None,
            "incremental_cost_bb": 1,
        },
    ]
    return state, str(row["public_fingerprint_sha256"])


def exact_support_view(protocol: Mapping[str, Any]) -> dict[str, Any]:
    report = _load(SUPPORT)
    expected_hash = protocol["exact_support_grid"]["source_report_hash"]
    actual_hash = (report.get("full_report") or {}).get("report_hash")
    if actual_hash != expected_hash:
        raise ValueError("TRAIN exact-support report hash drifted")
    rows = (
        report["kts_sb_two_limpers_projection"]["hero_public_context_support"][
            "observed_iso_targets"
        ]
    )
    by_target = {float(row["target_total_bb"]): int(row["observations"]) for row in rows}
    frozen_counts = {
        float(key): int(value)
        for key, value in protocol["exact_support_grid"][
            "hero_observed_support_by_target"
        ].items()
    }
    for target, expected in frozen_counts.items():
        if by_target.get(target) != expected:
            raise ValueError(
                f"exact-support count drifted for {target} BB: "
                f"{by_target.get(target)} != {expected}"
            )
    chosen = []
    for target in protocol["exact_support_grid"]["scientific_supported_targets_bb"]:
        n = by_target[float(target)]
        chosen.append(
            {
                "target_total_bb": float(target),
                "observations": n,
                "support_tier": "MEDIUM" if n >= 50 else "LOW",
                "identifiability": (
                    "IDENTIFIABLE_MARGINAL" if n >= 50 else "LOW_SUPPORT"
                ),
            }
        )
    return {
        "schema": "poker-preflop-exact-support-view/v1",
        "source_schema": report["schema"],
        "source_id": "issue-367:frozen-321-exact-support-intersection",
        "source_hash": actual_hash,
        "exact_price_only": True,
        "no_silent_nearest_price": True,
        "exact_target_support": chosen,
    }


def _budget(protocol: Mapping[str, Any]) -> AdaptiveBudget:
    cfg = protocol["paired_adaptive_budget"]
    return AdaptiveBudget(
        initial_samples_per_alternative=int(cfg["initial_samples_per_alternative"]),
        max_samples_per_alternative=int(cfg["max_samples_per_alternative"]),
        batch_size=int(cfg["batch_size"]),
        max_total_rollouts=int(cfg["max_total_rollouts"]),
        confidence_z=float(cfg["confidence_z"]),
        elimination_margin_bb=float(cfg["elimination_margin_bb"]),
    )


def summarize(result: Mapping[str, Any], protocol: Mapping[str, Any]) -> dict[str, Any]:
    diagnostics = {
        row["alternative_id"]: row for row in result["diagnostics"]["alternatives"]
    }
    indifference = {
        row["alternative_id"]: row
        for row in result["statistical_indifference"]
    }
    rows = []
    for alt in result["decision"]["alternatives"]:
        diag = diagnostics[alt["id"]]
        paired = alt.get("paired_delta_vs_selected")
        caller = diag.get("caller_partition")
        rows.append(
            {
                "alternative_id": alt["id"],
                "action": alt["action"],
                "target_total_bb": alt.get("target_total_bb"),
                "incremental_cost_bb": alt.get("incremental_cost_bb"),
                "support": alt.get("support"),
                "comparable": alt.get("comparable"),
                "ev_bb": alt.get("ev_bb"),
                "uncertainty": alt.get("uncertainty"),
                "delta_vs_best_paired": paired,
                "indifference_status": indifference[alt["id"]]["status"],
                "diagnostic_status": diag["status"],
                "p_all_fold": None if caller is None else caller["all_fold"],
                "p_1_caller": (
                    None if caller is None else caller["exactly_1_caller"]
                ),
                "p_2_callers": (
                    None if caller is None else caller["exactly_2_callers"]
                ),
                "p_3plus_callers": (
                    None if caller is None else caller["three_plus_callers"]
                ),
                "expected_callers": diag.get("expected_callers"),
                "p_3bet_or_jam": diag.get("p_3bet_or_jam"),
                "continuing_positions": diag.get("continuing_positions"),
                "posterior_refs": diag.get("posterior_refs"),
                "diagnostic_provenance": diag.get("provenance"),
            }
        )
    selected = str(result["decision"]["selected_id"])
    max_ev = max(
        float(row["ev_bb"])
        for row in rows
        if row["comparable"] is True and row["ev_bb"] is not None
    )
    selected_row = next(row for row in rows if row["alternative_id"] == selected)
    if float(selected_row["ev_bb"]) != max_ev:
        raise AssertionError("selected recommendation is not strict point max-EV")

    summary = {
        "schema": "poker-issue367-real-iso-ev-result/v1",
        "issue": 367,
        "parent_issue": 314,
        "protocol_sha256": _sha256(DEFAULT_PROTOCOL),
        "scenario": {
            "fixture": "kts_sb_two_limp_iso4_three_calls_v1",
            "hero_hand_class": "KTs",
            "hero_exact_cards": list(protocol["scenario"]["hero_exact_cards"]),
            "hero_position": "SB",
            "limpers": 2,
            "played_action": "ISO",
            "played_target_total_bb": 4.0,
        },
        "model_a": copy.deepcopy(protocol["model_a"]),
        "selection": {
            "rule": "MAX_EV_POINT_ESTIMATE_ONLY",
            "selected_alternative_id": selected,
            "selected_action": selected_row["action"],
            "selected_target_total_bb": selected_row["target_total_bb"],
            "selected_ev_bb": selected_row["ev_bb"],
            "indifference_rule": protocol["selection"]["indifference_rule"],
            "diagnostics_can_select": False,
        },
        "played_vs_recommended": {
            "played_alternative_id": "ISO@4",
            "played_scientific_status": next(
                row["support"]["status"]
                for row in rows
                if row["alternative_id"] == "ISO@4"
            ),
            "recommended_alternative_id": selected,
        },
        "alternatives": rows,
        "runner_result": copy.deepcopy(result),
        "scientific_boundary": {
            "test_consumed": False,
            "test_authorized": False,
            "model_b_consumed": False,
            "promotion_performed": False,
            "active_model_pointer_mutated": False,
            "ui_modified": False,
            "vs_limpers_generation_196": False,
        },
    }
    summary["result_sha256"] = _canonical_sha(summary)
    return summary


def summary_markdown(result: Mapping[str, Any]) -> str:
    selection = result["selection"]
    lines = [
        "# Issue #367 — real #314 canonical KTs ISO EV",
        "",
        f"- Decision: **{selection['selected_alternative_id']}** by strict max-EV.",
        f"- Selected EV: **{selection['selected_ev_bb']:.6f} BB**.",
        "- Model A: admitted sizing-aware v2 from #352, explicit identity binding.",
        "- Active Model A pointer: unchanged.",
        "- TEST: unconsumed / unauthorized.",
        "- Nearest-price: forbidden / unused.",
        "",
        "## Alternatives",
        "",
        "| Alternative | EV (BB) | 95% MC CI | Paired Δ vs best | Indifference | P(all fold) | P(1) | P(2) | P(3+) | E[callers] | P(3bet/jam) |",
        "|---|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in result["alternatives"]:
        unc = ((row.get("uncertainty") or {}).get("monte_carlo") or {})
        ci = (
            "—"
            if row["ev_bb"] is None
            else f"[{unc.get('ci95_low_bb'):.6f}, {unc.get('ci95_high_bb'):.6f}]"
        )
        delta = row.get("delta_vs_best_paired") or {}
        d = "—" if delta.get("delta_ev_bb") is None else f"{delta['delta_ev_bb']:.6f}"
        def f(value):
            return "—" if value is None else f"{float(value):.4f}"
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row["alternative_id"]),
                    "—" if row["ev_bb"] is None else f"{float(row['ev_bb']):.6f}",
                    ci,
                    d,
                    str(row["indifference_status"]),
                    f(row["p_all_fold"]),
                    f(row["p_1_caller"]),
                    f(row["p_2_callers"]),
                    f(row["p_3plus_callers"]),
                    f(row["expected_callers"]),
                    f(row["p_3bet_or_jam"]),
                ]
            )
            + " |"
        )
    lines += [
        "",
        "Caller diagnostics are defined by the existing #322 ISO diagnostics contract.",
        "FOLD/OVERLIMP therefore remain explicitly NOT_APPLICABLE for ISO caller-partition metrics.",
        "ISO prices that are legal/observed for Hero but lack admitted v2 exact response support remain LEGAL_BUT_UNSUPPORTED and receive no EV; no neighboring price is borrowed.",
        "",
    ]
    return "\n".join(lines)


def execute(protocol_path: Path) -> dict[str, Any]:
    if Path(protocol_path).resolve() != DEFAULT_PROTOCOL.resolve():
        raise ValueError("only the canonical frozen #367 protocol path is authorized")
    protocol = load_protocol(protocol_path)
    state, public_fingerprint = canonical_state()
    provider = Issue367ScientificProvider(
        hero_hole_cards=protocol["scenario"]["hero_exact_cards"],
        expected_candidate_sha256=protocol["model_a"]["candidate_sha256"],
        expected_decision=protocol["model_a"]["admission_decision"],
    )
    result = run_hero_preflop_iso(
        state_snapshot=state,
        public_state_fingerprint=public_fingerprint,
        requested_raise_targets_bb=protocol["exact_support_grid"][
            "requested_targets_bb"
        ],
        exact_support=exact_support_view(protocol),
        provider=provider,
        decision_id=protocol["execution"]["decision_id"],
        base_seed=protocol["execution"]["base_seed"],
        budget=_budget(protocol),
        execution_mode="SCIENTIFIC",
    )
    result["scientific_provider_audit"] = provider.audit()
    return summarize(result, protocol)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--summary", type=Path, required=True)
    p.add_argument("--print-marker", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    result = execute(args.protocol)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(summary_markdown(result), encoding="utf-8")
    if args.print_marker:
        print(
            "ISSUE367_RESULT="
            + json.dumps(result, sort_keys=True, separators=(",", ":"))
        )
    else:
        print(json.dumps(result["selection"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

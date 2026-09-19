#!/usr/bin/env python3
"""Certified TRAIN-only preflop sizing/price support audit for issue #319.

Only certified TRAIN hand IDs cross the hand-history parser boundary.
The audit is descriptive and never fits, selects, optimizes, promotes, or
mutates an active model.
"""
from __future__ import annotations

import argparse
import collections
import gzip
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.datasets.build_hand_history_increment import fingerprint, split_for
from tools.training.audit_hero_preflop_coverage import (
    DEFAULT_CERTIFICATION,
    load_train_records,
    support_tier,
)
from tools.training.increment_decisions import decision_rows, parse_hand

SCHEMA = "poker-preflop-sizing-support-audit/v1"
FOCUS_FAMILIES = (
    "UNOPENED",
    "VS_LIMPERS",
    "LIMPER_VS_ISO",
    "LIMPER_VS_ISO_CALLERS",
    "VS_ISO",
    "VS_ISO_CALLERS",
    "VS_RFI",
    "VS_RFI_CALLERS",
    "OPENER_OR_ISO_VS_3BET",
    "CALLER_VS_SQUEEZE_OR_3BET",
    "COLD_VS_3BET",
)
RESPONSES = ("FOLD", "CALL", "RAISE", "JAM")


def rounded(value: Any) -> float | None:
    if value is None:
        return None
    x = float(value)
    return round(x, 6) if math.isfinite(x) else None


def stable_hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(raw).hexdigest()


def normalize_action(action: Any) -> str:
    a = str(action or "").upper()
    return "CALL" if a == "LIMP" else a


def history_signature(history: list[dict[str, Any]]) -> str:
    return ">".join(str(x.get("position") or "") + ":" + str(x.get("action") or "") for x in history)


def history_features(history: list[dict[str, Any]]) -> tuple[str | None, int, int]:
    first_raise = next((i for i, x in enumerate(history) if x.get("action") in {"RAISE", "JAM"}), None)
    end = len(history) if first_raise is None else first_raise
    limpers = sum(1 for x in history[:end] if x.get("action") == "LIMP")
    callers = 0 if first_raise is None else sum(
        1 for x in history[first_raise + 1 :] if x.get("action") == "CALL"
    )
    aggs = [str(x.get("position") or "") for x in history if x.get("action") in {"RAISE", "JAM"}]
    return (aggs[-1] if aggs else None), limpers, callers


def empirical_bins(values: list[float | None], max_bins: int = 4) -> list[dict[str, Any]]:
    xs = sorted(x for x in (rounded(v) for v in values) if x is not None)
    if not xs:
        return []
    counts = collections.Counter(xs)
    unique = sorted(counts)
    bins = min(max_bins, len(unique))
    if bins == 1:
        return [{"bin_id": "B1", "min_observed": unique[0], "max_observed": unique[0], "observations": len(xs)}]
    total = len(xs)
    targets = [total * i / bins for i in range(1, bins)]
    result = []
    start = unique[0]
    running = 0
    bin_n = 0
    target_i = 0
    for i, value in enumerate(unique):
        n = counts[value]
        running += n
        bin_n += n
        last = i == len(unique) - 1
        split_here = target_i < len(targets) and running >= targets[target_i]
        if last or split_here:
            result.append({
                "bin_id": "B" + str(len(result) + 1),
                "min_observed": start,
                "max_observed": value,
                "observations": bin_n,
            })
            if split_here:
                target_i += 1
            if not last:
                start = unique[i + 1]
                bin_n = 0
    return result


def numeric_summary(values: list[float | None]) -> dict[str, Any]:
    xs = sorted(float(x) for x in values if x is not None and math.isfinite(float(x)))
    if not xs:
        return {"n": 0, "min": None, "p25": None, "p50": None, "p75": None, "max": None}
    def q(p: float) -> float:
        pos = p * (len(xs) - 1)
        lo, hi = math.floor(pos), math.ceil(pos)
        if lo == hi:
            return rounded(xs[lo])
        frac = pos - lo
        return rounded(xs[lo] * (1 - frac) + xs[hi] * frac)
    return {
        "n": len(xs),
        "min": rounded(xs[0]),
        "p25": q(.25),
        "p50": q(.50),
        "p75": q(.75),
        "max": rounded(xs[-1]),
    }


def action_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts = collections.Counter(normalize_action(r.get("action")) for r in rows)
    denom = sum(counts[a] for a in RESPONSES)
    return {
        "denominator": denom,
        "counts": {a: int(counts[a]) for a in RESPONSES},
        "rates": {a: (counts[a] / denom if denom else None) for a in RESPONSES},
        "check_count": int(counts["CHECK"]),
        "other_count": int(sum(n for a, n in counts.items() if a not in {*RESPONSES, "CHECK"})),
    }


def reveal_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    revealed = [r for r in rows if r.get("known_hand_class")]
    all_actions = action_summary(rows)
    rev_actions = action_summary(revealed)
    deltas = {}
    for action in RESPONSES:
        a = all_actions["rates"][action]
        b = rev_actions["rates"][action]
        deltas[action] = None if a is None or b is None else b - a
    n = len(rows)
    return {
        "marginal_decisions": n,
        "revealed_decisions": len(revealed),
        "unrevealed_decisions": n - len(revealed),
        "reveal_fraction": len(revealed) / n if n else None,
        "non_revealed_fraction": (n - len(revealed)) / n if n else None,
        "revealed_vs_marginal_action_rate_delta": deltas,
        "interpretation": "revealed hand classes are showdown/reveal-selected and are not representative of unrevealed marginal support",
    }


def prepare(row: dict[str, Any]) -> dict[str, Any]:
    history = list(row.get("history") or [])
    aggressor, limpers, callers = history_features(history)
    ctx = row.get("preflop_context_v1") or {}
    pot = rounded(row.get("pot_before_bb")) or 0.0
    to_call = rounded(row.get("to_call_bb")) or 0.0
    current_price = rounded(ctx.get("current_price_bb", row.get("current_price_bb")))
    sizing = row.get("action_sizing_v1") or {}
    return {
        **row,
        "_aggressor_position": aggressor,
        "_limper_count": limpers,
        "_caller_count": callers,
        "_action_sequence": history_signature(history),
        "_target_total_bb": current_price,
        "_to_call_bb": to_call,
        "_pot_before_bb": pot,
        "_price_to_pot": rounded(to_call / pot) if pot > 0 else None,
        "_pot_odds": rounded(to_call / (pot + to_call)) if pot + to_call > 0 else None,
        "_effective_stack_bb": rounded(ctx.get("effective_stack_bb")),
        "_observed_action_target_total_bb": rounded(sizing.get("target_total_bb")),
    }


def context_key(r: dict[str, Any]) -> tuple[Any, ...]:
    return (
        str(r.get("family") or ""),
        str(r.get("actor_position") or ""),
        r["_aggressor_position"] or "",
        int(r["_limper_count"]),
        int(r["_caller_count"]),
        r["_target_total_bb"],
        r["_to_call_bb"],
    )


def context_matrix(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for r in rows:
        grouped.setdefault(context_key(r), []).append(r)
    out = []
    for key, group in grouped.items():
        family, actor, aggressor, limpers, callers, target, to_call = key
        sequences = collections.Counter(r["_action_sequence"] for r in group)
        observed_sizings = collections.Counter(
            r["_observed_action_target_total_bb"]
            for r in group if r["_observed_action_target_total_bb"] is not None
        )
        out.append({
            "family": family,
            "actor_position": actor,
            "aggressor_position": aggressor or None,
            "limper_count": limpers,
            "caller_count": callers,
            "target_total_bb": target,
            "to_call_bb": to_call,
            "observations": len(group),
            "distinct_hands": len({str(r["hand_id"]) for r in group}),
            "hand_ids_fingerprint_sha256": fingerprint({str(r["hand_id"]) for r in group}),
            "support_tier": support_tier(len(group)),
            "identifiability": (
                "IDENTIFIABLE_MARGINAL" if len(group) >= 50 else
                "BACKOFF_RECOMMENDED" if len(group) >= 20 else
                "LOW_SUPPORT"
            ),
            "actions": action_summary(group),
            "reveal": reveal_summary(group),
            "pot_before_bb": numeric_summary([r["_pot_before_bb"] for r in group]),
            "price_to_pot": numeric_summary([r["_price_to_pot"] for r in group]),
            "pot_odds": numeric_summary([r["_pot_odds"] for r in group]),
            "effective_stack_bb": numeric_summary([r["_effective_stack_bb"] for r in group]),
            "action_sequences": [
                {"sequence": s, "observations": n}
                for s, n in sorted(sequences.items(), key=lambda kv: (-kv[1], kv[0]))
            ],
            "observed_raise_or_jam_targets": [
                {"target_total_bb": s, "observations": n}
                for s, n in sorted(observed_sizings.items(), key=lambda kv: (-kv[1], kv[0]))
            ],
        })
    return sorted(out, key=lambda x: (
        -x["observations"], x["family"], x["actor_position"],
        x["aggressor_position"] or "", x["limper_count"], x["caller_count"],
        -1 if x["target_total_bb"] is None else x["target_total_bb"],
        x["to_call_bb"],
    ))


def hand_class_support(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for r in rows:
        hc = r.get("known_hand_class")
        if hc:
            grouped.setdefault(context_key(r) + (str(hc),), []).append(r)
    out = []
    for key, group in grouped.items():
        family, actor, aggressor, limpers, callers, target, to_call, hand_class = key
        out.append({
            "family": family,
            "actor_position": actor,
            "aggressor_position": aggressor or None,
            "limper_count": limpers,
            "caller_count": callers,
            "target_total_bb": target,
            "to_call_bb": to_call,
            "hand_class": hand_class,
            "revealed_observations": len(group),
            "actions": action_summary(group),
        })
    return sorted(out, key=lambda x: (
        -x["revealed_observations"], x["family"], x["actor_position"], x["hand_class"],
        -1 if x["target_total_bb"] is None else x["target_total_bb"],
    ))


def bin_proposals(rows: list[dict[str, Any]]) -> dict[str, Any]:
    result = {}
    for family in FOCUS_FAMILIES:
        group = [r for r in rows if r.get("family") == family]
        result[family] = {
            "method": "EMPIRICAL_EQUAL_MASS_OBSERVED_BOUNDARIES",
            "target_total_bb": empirical_bins([r["_target_total_bb"] for r in group]),
            "to_call_bb": empirical_bins([r["_to_call_bb"] for r in group]),
            "pot_before_bb": empirical_bins([r["_pot_before_bb"] for r in group]),
            "price_to_pot": empirical_bins([r["_price_to_pot"] for r in group]),
            "effective_stack_bb": empirical_bins([r["_effective_stack_bb"] for r in group]),
            "observed_action_target_total_bb": empirical_bins([
                r["_observed_action_target_total_bb"] for r in group
            ]),
        }
    return result


def kts_projection(rows: list[dict[str, Any]]) -> dict[str, Any]:
    sb = [
        r for r in rows
        if r.get("family") == "VS_LIMPERS"
        and r.get("actor_position") == "SB"
        and r["_limper_count"] == 2
    ]
    iso_targets = collections.Counter(
        r["_observed_action_target_total_bb"]
        for r in sb
        if r.get("action") in {"RAISE", "JAM"} and r["_observed_action_target_total_bb"] is not None
    )
    responses = [
        r for r in rows
        if r["_aggressor_position"] == "SB"
        and r["_limper_count"] == 2
        and r.get("family") in {"LIMPER_VS_ISO", "LIMPER_VS_ISO_CALLERS", "VS_ISO", "VS_ISO_CALLERS"}
    ]
    by_price: dict[float | None, list[dict[str, Any]]] = {}
    for r in responses:
        by_price.setdefault(r["_target_total_bb"], []).append(r)
    response_support = []
    for price, group in sorted(by_price.items(), key=lambda kv: (-1 if kv[0] is None else kv[0])):
        by_responder = []
        responder_groups: dict[tuple[str, int], list[dict[str, Any]]] = {}
        for r in group:
            responder_groups.setdefault((str(r.get("actor_position") or ""), int(r["_caller_count"])), []).append(r)
        for (position, caller_count), sub in sorted(responder_groups.items()):
            by_responder.append({
                "actor_position": position,
                "caller_count": caller_count,
                "observations": len(sub),
                "actions": action_summary(sub),
            })
        response_support.append({
            "target_total_bb": price,
            "observations": len(group),
            "distinct_hands": len({str(r["hand_id"]) for r in group}),
            "support_tier": support_tier(len(group)),
            "actions": action_summary(group),
            "reveal": reveal_summary(group),
            "by_responder_context": by_responder,
        })
    exact = {x["target_total_bb"]: x for x in response_support}
    requested = []
    for price in (4.0, 5.0, 6.0):
        x = exact.get(price)
        requested.append({
            "target_total_bb": price,
            "state": "EXACT_SUPPORT" if x else "NO_EXACT_SUPPORT",
            "observations": x["observations"] if x else 0,
            "support_tier": x["support_tier"] if x else "NONE",
        })
    return {
        "scenario": {
            "hero_hand_class": "KTs",
            "hero_position": "SB",
            "limper_count": 2,
            "public_context_only": True,
            "opponent_hidden_cards_consumed": False,
            "hero_hand_used_to_filter_opponent_rows": False,
        },
        "hero_public_context_support": {
            "observations": len(sb),
            "actions": action_summary(sb),
            "observed_iso_targets": [
                {"target_total_bb": s, "observations": n}
                for s, n in sorted(iso_targets.items(), key=lambda kv: (-kv[1], kv[0]))
            ],
        },
        "opponent_response_support_by_exact_price": response_support,
        "requested_4_5_6bb_exact_support": requested,
        "interpretation": "KTs labels the Hero use case only; opponent response rows use public context and never hidden opponent cards",
    }


def analyze_rows(rows: list[dict[str, Any]], provenance: dict[str, Any] | None = None) -> dict[str, Any]:
    for r in rows:
        if r.get("split") != "TRAIN":
            raise AssertionError("non-TRAIN row supplied")
        if r.get("street") != "preflop":
            raise AssertionError("non-preflop row supplied")
        if r.get("is_hero"):
            raise AssertionError("Hero row supplied to population audit")
    prepared = [prepare(r) for r in rows if str(r.get("family") or "") in FOCUS_FAMILIES]
    matrix = context_matrix(prepared)
    reveals = reveal_summary(prepared)
    report = {
        "schema": SCHEMA,
        "population_id": "pokerstars_nlhe_100-200_zoom_play_6max_v1",
        "scope": {
            "split_consumed": "TRAIN",
            "validation_consumed": False,
            "test_consumed": False,
            "issue_108_consumed": False,
            "active_model_consumed": False,
            "active_model_modified": False,
            "optimization_performed": False,
            "ui_modified": False,
        },
        "provenance": provenance or {},
        "semantics": {
            "target_total_bb": "public current_price_bb before the response",
            "observed_action_target_total_bb": "real parser-derived RAISE/JAM target",
            "sizing_reconstructed_from_fixed_grid": False,
            "hand_class_support_is_reveal_selected": True,
            "scientific_effect": "NONE_ANALYTICS_ONLY",
            "consumable_by": ["#313", "#315"],
        },
        "accounting": {
            "population_preflop_rows_in_scope": len(prepared),
            "distinct_hands_in_scope": len({str(r["hand_id"]) for r in prepared}),
            "revealed_rows": reveals["revealed_decisions"],
            "unrevealed_rows": reveals["unrevealed_decisions"],
            "reveal_fraction": reveals["reveal_fraction"],
        },
        "bin_proposals": bin_proposals(prepared),
        "backoff_contract": {
            "no_silent_nearest_price": True,
            "exact_price_first": True,
            "ordered_backoff": [
                "exact public context plus exact target_total_bb",
                "drop action_sequence detail",
                "drop caller_count",
                "drop aggressor_position",
                "family plus exact target_total_bb",
                "family plus explicitly declared empirical sizing bin",
            ],
            "identifiability": {
                "IDENTIFIABLE_MARGINAL": ">=50 observations",
                "BACKOFF_RECOMMENDED": "20-49 observations",
                "LOW_SUPPORT": "1-19 observations",
                "NO_SUPPORT": "0 observations",
            },
        },
        "matrix": matrix,
        "revealed_hand_class_support": hand_class_support(prepared),
        "reveal_bias": reveals,
        "kts_sb_two_limpers_projection": kts_projection(prepared),
        "support_zone_summary": dict(sorted(collections.Counter(x["identifiability"] for x in matrix).items())),
    }
    report["report_hash"] = stable_hash(report)
    return report


def audit(certification_path: Path = DEFAULT_CERTIFICATION) -> dict[str, Any]:
    records, provenance = load_train_records(certification_path)
    train_ids = {str(r.hand_id) for r in records}
    expected = int(provenance["certified_split_counts"]["TRAIN"])
    if len(train_ids) != expected:
        raise AssertionError("certified TRAIN hand count mismatch")
    rows = []
    parsed = 0
    for record in records:
        if split_for(record.hand_id) != "TRAIN":
            raise AssertionError("non-TRAIN hand crossed parser boundary")
        hand = parse_hand(record.text, record.source_file)
        if not hand:
            raise ValueError("TRAIN hand failed normalization: " + str(record.hand_id))
        parsed += 1
        for row in decision_rows(hand, include_preflop_context_v1=True):
            if row.get("split") != "TRAIN":
                raise AssertionError("non-TRAIN decision produced")
            if row.get("street") == "preflop" and not row.get("is_hero"):
                rows.append(row)
    provenance = {
        **provenance,
        "train_hand_count": len(train_ids),
        "train_hand_ids_fingerprint_sha256": fingerprint(train_ids),
        "decision_parser": "tools/training/increment_decisions.py::decision_rows(include_preflop_context_v1=True)",
    }
    report = analyze_rows(rows, provenance)
    report["accounting"]["train_hands_expected"] = expected
    report["accounting"]["train_hands_parsed"] = parsed
    report["report_hash"] = stable_hash({k: v for k, v in report.items() if k != "report_hash"})
    return report


def summary_report(report: dict[str, Any], full_report_path: str = "analysis/preflop_sizing_support_train.full.json.gz") -> dict[str, Any]:
    return {
        "schema": "poker-preflop-sizing-support-audit-summary/v1",
        "population_id": report["population_id"],
        "scope": report["scope"],
        "provenance": report["provenance"],
        "semantics": report["semantics"],
        "accounting": report["accounting"],
        "bin_proposals": report["bin_proposals"],
        "backoff_contract": report["backoff_contract"],
        "support_zone_summary": report["support_zone_summary"],
        "kts_sb_two_limpers_projection": report["kts_sb_two_limpers_projection"],
        "top_matrix_cells": report["matrix"][:100],
        "full_report": {
            "path": full_report_path,
            "compression": "gzip",
            "content_schema": report["schema"],
            "report_hash": report["report_hash"],
            "matrix_cells": len(report["matrix"]),
            "revealed_hand_class_cells": len(report["revealed_hand_class_support"]),
        },
    }


def render_markdown(report: dict[str, Any]) -> str:
    a = report["accounting"]
    p = report["kts_sb_two_limpers_projection"]
    lines = [
        "# Preflop sizing / price support — certified TRAIN audit",
        "",
        "Descriptive TRAIN-only audit. No TEST, #108, active model, optimization, promotion, or UI effect.",
        "",
        "## Accounting",
        "",
        "- Certified TRAIN hands parsed: " + str(a.get("train_hands_parsed", "n/a")),
        "- Population preflop rows in requested families: " + str(a["population_preflop_rows_in_scope"]),
        "- Distinct hands represented: " + str(a["distinct_hands_in_scope"]),
        "- Revealed rows: " + str(a["revealed_rows"]),
        "- Unrevealed rows: " + str(a["unrevealed_rows"]),
        "- Reveal fraction: " + format(a["reveal_fraction"] or 0, ".4f"),
        "- TEST_CONSUMED=false",
        "",
        "## Sizing semantics",
        "",
        "- target_total_bb is the real public current price before a response.",
        "- observed_action_target_total_bb is the real parsed raise/jam target.",
        "- No fixed sizing grid is reconstructed.",
        "- Empirical bins use observed equal-mass boundaries.",
        "- Fold/call/raise/jam rates include their denominators.",
        "- Revealed hand-class support is separate from marginal support.",
        "",
        "## Support zones",
        "",
    ]
    for k, v in report["support_zone_summary"].items():
        lines.append("- " + k + ": " + str(v) + " cells")
    lines += [
        "",
        "## KTs SB + two limpers",
        "",
        "KTs is only the Hero use-case label. Opponent hidden cards are never used.",
        "- SB public-context observations: " + str(p["hero_public_context_support"]["observations"]),
        "- Observed SB iso targets: " + ", ".join(
            format(x["target_total_bb"], "g") + " BB (n=" + str(x["observations"]) + ")"
            for x in p["hero_public_context_support"]["observed_iso_targets"][:20]
        ),
        "- Exact opponent response support:",
    ]
    for x in p["requested_4_5_6bb_exact_support"]:
        lines.append(
            "  - " + format(x["target_total_bb"], "g") + " BB: " + x["state"] +
            " (n=" + str(x["observations"]) + ", " + x["support_tier"] + ")"
        )
    lines += [
        "",
        "## Highest-support exact price/context cells",
        "",
        "| Family | Actor | Aggressor | Limpers | Callers | Target | To call | Obs | Tier |",
        "|---|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for x in report["matrix"][:50]:
        lines.append(
            "| " + x["family"] + " | " + x["actor_position"] + " | " +
            (x["aggressor_position"] or "—") + " | " + str(x["limper_count"]) + " | " +
            str(x["caller_count"]) + " | " + str(x["target_total_bb"]) + " | " +
            str(x["to_call_bb"]) + " | " + str(x["observations"]) + " | " + x["support_tier"] + " |"
        )
    lines += [
        "",
        "## Backoff contract for #313 / #315",
        "",
        "- Exact price support first.",
        "- No silent nearest-price substitution.",
        "- Any dimension-dropping or empirical-bin backoff must be explicit.",
        "- Revealed hand classes are reveal-selected; marginal support remains the coverage reference.",
        "",
        "Reproduction:",
        "python3 tools/training/audit_preflop_sizing_support.py --output-json analysis/preflop_sizing_support_train.json --output-md analysis/preflop_sizing_support_train.md --full-json-gz analysis/preflop_sizing_support_train.full.json.gz",
        "",
        "Report hash: " + report["report_hash"],
        "",
    ]
    return "\n".join(lines)


def canonical_report_bytes(report: dict[str, Any]) -> bytes:
    return (json.dumps(report, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def write_outputs(
    report: dict[str, Any],
    json_path: Path,
    md_path: Path,
    full_json_gz_path: Path,
) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    full_json_gz_path.parent.mkdir(parents=True, exist_ok=True)
    summary = summary_report(
        report,
        full_json_gz_path.relative_to(ROOT).as_posix() if full_json_gz_path.is_relative_to(ROOT) else str(full_json_gz_path),
    )
    json_path.write_text(json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    full_json_gz_path.write_bytes(gzip.compress(canonical_report_bytes(report), mtime=0))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--certification", type=Path, default=DEFAULT_CERTIFICATION)
    parser.add_argument("--output-json", type=Path)
    parser.add_argument("--output-md", type=Path)
    parser.add_argument("--full-json-gz", type=Path)
    parser.add_argument("--print-json", action="store_true")
    args = parser.parse_args()
    cert = args.certification if args.certification.is_absolute() else ROOT / args.certification
    report = audit(cert)
    if args.output_json or args.output_md or args.full_json_gz:
        if not (args.output_json and args.output_md and args.full_json_gz):
            raise SystemExit("--output-json, --output-md and --full-json-gz must be supplied together")
        jp = args.output_json if args.output_json.is_absolute() else ROOT / args.output_json
        mp = args.output_md if args.output_md.is_absolute() else ROOT / args.output_md
        gp = args.full_json_gz if args.full_json_gz.is_absolute() else ROOT / args.full_json_gz
        write_outputs(report, jp, mp, gp)
    if args.print_json:
        print(json.dumps(report, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
    else:
        print(json.dumps({
            "schema": report["schema"],
            "report_hash": report["report_hash"],
            "accounting": report["accounting"],
            "support_zone_summary": report["support_zone_summary"],
            "kts": report["kts_sb_two_limpers_projection"]["requested_4_5_6bb_exact_support"],
        }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

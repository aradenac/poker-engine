#!/usr/bin/env python3
"""Fit and VALIDATION-only evaluation for issue #339 sizing-aware Model A.

The fit consumes the persisted #319 certified TRAIN support report.  VALIDATION
is loaded only after the frozen protocol has been checked.  TEST is never read.
No production pointer or active model is mutated by this program.
"""
from __future__ import annotations

import argparse
import collections
import gzip
import hashlib
import json
import math
import random
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.datasets.build_hand_history_increment import (
    fingerprint,
    read_archive,
    sha256_file,
    split_for,
)
from tools.preflop.model_a_sizing_likelihood import (
    BACKOFF_POLICY,
    PUBLIC_CONTEXT_SCHEMA,
    SCHEMA,
    candidate_identity,
    canonical_candidate_sha256,
    sizing_context_key,
    support_context_key,
    validate_candidate,
)
from tools.training.audit_preflop_sizing_support import FOCUS_FAMILIES
from tools.training.evaluate_preflop_topology_candidate import by_actor, find_closest
from tools.training.increment_decisions import decision_rows, parse_hand
from tools.training.preflop_policy169 import (
    decode_policy169,
    hand_weights,
    policy_probability,
)
from src.ranges.model_a_posterior_runtime import ModelAPosteriorRuntime
from src.ranges.posterior_range import validate_posterior_range
from tools.preflop.model_a_sizing_runtime import SizingAwareModelAContinuationPolicy
from tools.repro_preflop_fixture import load_verified_reference
from tools.simulation.game_core import NoLimitHoldemState

PROTOCOL = ROOT / "analysis/model_a_preflop_sizing_validation_protocol.json"
SUPPORT_SUMMARY = ROOT / "analysis/preflop_sizing_support_train.json"
SUPPORT_FULL = ROOT / "analysis/preflop_sizing_support_train.full.json.gz"
CERTIFICATION = ROOT / "training/datasets/NLHE_100-200/population_certification.json"
REFERENCE = ROOT / "training/models/preflop_population_model_v5.json"
EXPECTED_SUPPORT_HASH = "5db39f3e461431f2c3cba9417cdf96f5b53437304b166e1886b3f2d9764c7f99"
EXPECTED_REFERENCE_HASH = "ff952055ca4ee051a3ac9607d513fdecac0a320a31f658ecfd8a11d8448975ca"
ACTIONS = ("FOLD", "CALL", "RAISE", "JAM")
EPS = 1e-12


def canonical_hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(raw).hexdigest()


def percentile(values: Sequence[float], q: float) -> float:
    xs = sorted(float(x) for x in values)
    if not xs:
        return 0.0
    pos = (len(xs) - 1) * q
    lo, hi = int(math.floor(pos)), int(math.ceil(pos))
    if lo == hi:
        return xs[lo]
    return xs[lo] * (hi - pos) + xs[hi] * (pos - lo)


def bootstrap(rows: list[dict[str, Any]], *, samples: int, seed: int) -> dict[str, Any]:
    grouped: dict[str, list[float]] = collections.defaultdict(list)
    for row in rows:
        grouped[str(row["hand_id"])].append(float(row["delta_nll"]))
    hands = sorted(grouped)
    if not hands:
        return {
            "hands": 0,
            "samples": samples,
            "seed": seed,
            "mean": 0.0,
            "ci95": [0.0, 0.0],
            "probability_candidate_better": 0.0,
        }
    rng = random.Random(seed)
    draws: list[float] = []
    for _ in range(samples):
        total = 0.0
        n = 0
        for _slot in hands:
            hid = hands[rng.randrange(len(hands))]
            vals = grouped[hid]
            total += sum(vals)
            n += len(vals)
        draws.append(total / max(1, n))
    mean = sum(float(row["delta_nll"]) for row in rows) / len(rows)
    return {
        "hands": len(hands),
        "samples": samples,
        "seed": seed,
        "mean": mean,
        "ci95": [percentile(draws, 0.025), percentile(draws, 0.975)],
        "probability_candidate_better": sum(x < 0 for x in draws) / len(draws),
    }


def load_protocol() -> dict[str, Any]:
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    if protocol.get("schema") != "poker-model-a-preflop-sizing-validation-protocol/v1":
        raise ValueError("unexpected #339 protocol schema")
    if protocol.get("status") != "FROZEN_BEFORE_VALIDATION":
        raise ValueError("#339 protocol must be frozen before VALIDATION")
    if (protocol.get("evaluation") or {}).get("split") != "VALIDATION":
        raise ValueError("#339 selection split must be VALIDATION")
    if (protocol.get("evaluation") or {}).get("test_consumed") is not False:
        raise ValueError("TEST must stay unconsumed")
    if (protocol.get("evaluation") or {}).get("test_authorized") is not False:
        raise ValueError("#339 may not authorize TEST")
    return protocol


def load_support_report() -> tuple[dict[str, Any], dict[str, Any]]:
    summary = json.loads(SUPPORT_SUMMARY.read_text(encoding="utf-8"))
    if ((summary.get("full_report") or {}).get("report_hash")) != EXPECTED_SUPPORT_HASH:
        raise ValueError("#319 summary report hash drifted")
    with gzip.open(SUPPORT_FULL, "rt", encoding="utf-8") as handle:
        report = json.load(handle)
    if report.get("schema") != "poker-preflop-sizing-support-audit/v1":
        raise ValueError("unexpected #319 full report schema")
    if report.get("report_hash") != EXPECTED_SUPPORT_HASH:
        raise ValueError("#319 full report hash drifted")
    scope = report.get("scope") or {}
    if scope.get("split_consumed") != "TRAIN" or scope.get("test_consumed") is not False:
        raise ValueError("#319 support report must remain TRAIN-only")
    if (report.get("backoff_contract") or {}).get("no_silent_nearest_price") is not True:
        raise ValueError("#319 no-nearest-price contract missing")
    return summary, report


def _median(stats: Mapping[str, Any] | None, default: float = 0.0) -> float:
    stats = stats or {}
    for key in ("p50", "median", "mean"):
        value = stats.get(key)
        if isinstance(value, (int, float)) and math.isfinite(float(value)):
            return float(value)
    return float(default)


def _support_mapping(cell: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "family": str(cell.get("family") or ""),
        "actor_position": str(cell.get("actor_position") or ""),
        "aggressor_position": cell.get("aggressor_position"),
        "limper_count": int(cell.get("limper_count") or 0),
        "caller_count": int(cell.get("caller_count") or 0),
        "target_total_bb": float(cell.get("target_total_bb") or 0.0),
        "to_call_bb": float(cell.get("to_call_bb") or 0.0),
    }


def _representative_public_context(cell: Mapping[str, Any], support_key: str) -> dict[str, Any]:
    target = float(cell.get("target_total_bb") or 0.0)
    to_call = float(cell.get("to_call_bb") or 0.0)
    pot = _median(cell.get("pot_before_bb"))
    eff = _median(cell.get("effective_stack_bb"))
    ratio = None if pot <= EPS else to_call / pot
    odds = 0.0 if pot + to_call <= EPS else to_call / (pot + to_call)
    representative = {
        "schema": PUBLIC_CONTEXT_SCHEMA,
        "state_timing": "BEFORE_ACTION",
        "table_size": 6,
        "actor_position": str(cell.get("actor_position") or ""),
        "family": str(cell.get("family") or ""),
        "aggressor_position": cell.get("aggressor_position"),
        "raise_level": 0,
        "structural_key": "support:#319:" + support_key,
        "target_total_bb": target,
        "to_call_bb": to_call,
        "pot_before_bb": pot,
        "price_to_pot_ratio": ratio,
        "pot_odds": odds,
        "effective_stack_bb": eff,
        "limper_count": int(cell.get("limper_count") or 0),
        "caller_count": int(cell.get("caller_count") or 0),
        "information_boundary": {
            "public_only": True,
            "future_cards_consumed": False,
            "opponent_hole_cards_consumed": False,
        },
    }
    representative["sizing_context_key"] = sizing_context_key(representative)
    representative["support_context_key"] = support_key
    return representative


def _jeffreys(counts: Mapping[str, Any], alpha: float) -> dict[str, float]:
    values = {action: max(0, int(counts.get(action) or 0)) for action in ACTIONS}
    denom = sum(values.values()) + alpha * len(ACTIONS)
    if denom <= 0:
        raise ValueError("empty action support")
    return {action: (values[action] + alpha) / denom for action in ACTIONS}


def build_candidate(protocol: Mapping[str, Any], report: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    fit = protocol["candidate_fit"]
    support_cfg = protocol["train_support"]
    min_marginal = int(support_cfg["minimum_marginal_observations"])
    min_hand = int(support_cfg["minimum_revealed_hand_class_observations"])
    alpha = float(fit["marginal_estimator"]["alpha_per_action"])
    hand_prior = float(fit["hand_class_estimator"]["prior_strength"])

    marginal_nodes: dict[str, dict[str, Any]] = {}
    nodes: list[dict[str, Any]] = []
    for cell in report.get("matrix") or []:
        observations = int(cell.get("observations") or 0)
        if observations < min_marginal:
            continue
        support_key = support_context_key(_support_mapping(cell))
        probabilities = _jeffreys((cell.get("actions") or {}).get("counts") or {}, alpha)
        node = {
            "node_id": "MAPM_" + hashlib.sha256(support_key.encode()).hexdigest()[:16],
            "sizing_context_key": _representative_public_context(cell, support_key)["sizing_context_key"],
            "support_context_key": support_key,
            "public_context": _representative_public_context(cell, support_key),
            "hand_class": None,
            "probabilities": probabilities,
            "support": observations,
            "support_denominator": int((cell.get("actions") or {}).get("denominator") or observations),
            "support_class": str(cell.get("identifiability") or "BACKOFF_RECOMMENDED"),
            "source_report_hash": EXPECTED_SUPPORT_HASH,
            "fit_method": f"JEFFREYS_DIRICHLET_ALPHA_{alpha:g}",
            "reveal_bias": {
                "reveal_selected": False,
                "reveal_fraction": (cell.get("reveal") or {}).get("reveal_fraction"),
            },
        }
        marginal_nodes[support_key] = node
        nodes.append(node)

    hand_nodes = 0
    for cell in report.get("revealed_hand_class_support") or []:
        n = int(cell.get("revealed_observations") or 0)
        if n < min_hand:
            continue
        support_key = support_context_key(_support_mapping(cell))
        marginal = marginal_nodes.get(support_key)
        if marginal is None:
            continue
        counts = (cell.get("actions") or {}).get("counts") or {}
        raw = {action: max(0, int(counts.get(action) or 0)) for action in ACTIONS}
        denom = sum(raw.values()) + hand_prior
        if denom <= 0:
            continue
        probabilities = {
            action: (raw[action] + hand_prior * float(marginal["probabilities"][action])) / denom
            for action in ACTIONS
        }
        node = {
            "node_id": "MAPH_" + hashlib.sha256((support_key + "|" + str(cell["hand_class"])).encode()).hexdigest()[:16],
            "sizing_context_key": marginal["sizing_context_key"],
            "support_context_key": support_key,
            "public_context": dict(marginal["public_context"]),
            "hand_class": str(cell["hand_class"]),
            "probabilities": probabilities,
            "support": n,
            "support_denominator": n,
            "support_class": "IDENTIFIABLE_REVEAL_SELECTED_HAND_CLASS",
            "source_report_hash": EXPECTED_SUPPORT_HASH,
            "fit_method": f"REVEALED_CLASS_SHRUNK_TO_EXACT_PRICE_MARGINAL_PRIOR_{hand_prior:g}",
            "reveal_bias": {
                "reveal_selected": True,
                "reveal_fraction": (marginal.get("reveal_bias") or {}).get("reveal_fraction"),
            },
        }
        nodes.append(node)
        hand_nodes += 1

    candidate = {
        "schema": SCHEMA,
        "identity": candidate_identity(
            population_id=str(report["population_id"]),
            fit_scope="TRAIN_EMPIRICAL_FIT",
            data_scope="CERTIFIED_TRAIN_ONLY",
            source_report_hash=EXPECTED_SUPPORT_HASH,
        ),
        "backoff_policy": list(BACKOFF_POLICY),
        "nearest_price_fallback": False,
        "nodes": sorted(
            nodes,
            key=lambda node: (
                str(node.get("support_context_key") or ""),
                "" if node.get("hand_class") is None else str(node["hand_class"]),
            ),
        ),
    }
    validate_candidate(candidate)
    candidate_sha = canonical_candidate_sha256(candidate)
    kts = report.get("kts_sb_two_limpers_projection") or {}
    kts_support = list(kts.get("requested_4_5_6bb_exact_support") or [])
    fit_evidence = {
        "schema": "poker-model-a-preflop-sizing-fit-evidence/v1",
        "issue": 339,
        "population_id": report["population_id"],
        "split_consumed": "TRAIN",
        "validation_consumed": False,
        "test_consumed": False,
        "source_support_report_hash": EXPECTED_SUPPORT_HASH,
        "candidate_sha256": candidate_sha,
        "candidate_identity": candidate["identity"],
        "nodes": {
            "total": len(candidate["nodes"]),
            "marginal_exact_price": len(marginal_nodes),
            "identifiable_revealed_hand_class": hand_nodes,
        },
        "fit": {
            "minimum_marginal_observations": min_marginal,
            "minimum_revealed_hand_class_observations": min_hand,
            "marginal_alpha_per_action": alpha,
            "revealed_hand_prior_strength": hand_prior,
            "nearest_price_fallback": False,
            "backoff_policy": list(BACKOFF_POLICY),
        },
        "reveal_bias": {
            "source_reveal_fraction": (report.get("accounting") or {}).get("reveal_fraction"),
            "hand_class_rows_are_reveal_selected": True,
            "hidden_hands_imputed": False,
        },
        "kts_sb_two_limpers_exact_price_support": kts_support,
        "production_effect": "NONE",
        "active_model_replaced": False,
        "reproduction": "python3 tools/training/fit_model_a_preflop_sizing.py --phase fit",
    }
    fit_evidence["evidence_sha256"] = canonical_hash(fit_evidence)
    return candidate, fit_evidence


def evaluate_kts_posterior(candidate: Mapping[str, Any]) -> dict[str, Any]:
    """Exercise the canonical #321 public fixture at exact 4/5/6 BB prices."""
    fixture = load_verified_reference(ROOT)
    scenario = fixture["scenario"]
    candidate_sha = canonical_candidate_sha256(candidate)
    rows = []
    for target in (4.0, 5.0, 6.0):
        state = NoLimitHoldemState(
            seats=scenario["seats"],
            button=scenario["button"],
            stacks_bb=scenario["starting_stacks_bb"],
            small_blind_bb=scenario["blinds_bb"]["small"],
            big_blind_bb=scenario["blinds_bb"]["big"],
        )
        for action in scenario["actions"][:4]:
            state.apply_action(str(action["player"]), str(action["action"]).upper())
        state.apply_action("Hero", "RAISE", target_total_bb=target)
        policy = SizingAwareModelAContinuationPolicy(candidate)
        runtime = ModelAPosteriorRuntime(
            policy,
            population_id=str(candidate["identity"]["population_id"]),
            model_id=str(candidate["identity"]["candidate_id"]),
            model_version=candidate_sha[:16],
            source_id="analysis/preflop_sizing_support_train.full.json.gz#report_hash=" + EXPECTED_SUPPORT_HASH,
        )
        before = runtime.posterior_record(
            state,
            player="BB",
            moment="BEFORE_ACTION",
            hand_id=str(fixture["scenario_id"]) + f"@{target:g}bb",
            step_id=f"bb_call_iso:{target:g}:before",
        )
        state.apply_action("BB", "CALL")
        after = runtime.posterior_record(
            state,
            player="BB",
            moment="AFTER_ACTION",
            hand_id=str(fixture["scenario_id"]) + f"@{target:g}bb",
            step_id=f"bb_call_iso:{target:g}:after",
        )
        before_errors = validate_posterior_range(before)
        after_errors = validate_posterior_range(after)
        if before_errors or after_errors:
            raise ValueError(
                f"#320 posterior contract failed at {target:g} BB: "
                f"before={before_errors} after={after_errors}"
            )
        rows.append({
            "target_total_bb": target,
            "before_status": before["status"],
            "after_status": after["status"],
            "after_reason": after.get("reason"),
            "source_observations": int((after.get("support") or {}).get("source_observations") or 0),
            "backoff_level": (after.get("support") or {}).get("backoff", {}).get("level"),
            "public_action": after.get("public_action"),
            "candidate_identity": after.get("identity"),
            "provenance": after.get("provenance"),
            "contract_errors": [],
        })
    return {
        "schema": "poker-model-a-preflop-sizing-posterior-evidence/v1",
        "fixture": fixture["scenario_id"],
        "posterior_contract": "poker-opponent-posterior-range/v1",
        "public_only": True,
        "future_cards_consumed": False,
        "opponent_hole_cards_consumed": False,
        "candidate_sha256": candidate_sha,
        "prices": rows,
        "expectation": "4/5/6 are independent exact-price contexts; low support fails closed rather than borrowing a neighboring price",
    }


def load_certified_split(split: str) -> tuple[list[Any], dict[str, Any]]:
    if split not in {"TRAIN", "VALIDATION"}:
        raise ValueError("#339 loader only permits TRAIN or VALIDATION; TEST is forbidden")
    cert = json.loads(CERTIFICATION.read_text(encoding="utf-8"))
    if cert.get("schema") != "poker-population-certification/v1":
        raise ValueError("unexpected certification schema")
    status = cert.get("status") or {}
    admissible = status.get("ADMISSIBLE") or {}
    excluded = status.get("EXCLUDED") or {}
    ambiguous = status.get("AMBIGUOUS") or {}
    if int(ambiguous.get("unique_hands") or 0):
        raise ValueError("AMBIGUOUS certified hands present")
    by_id: dict[str, Any] = {}
    archive_evidence = []
    for archive in cert.get("archives") or []:
        rel = str(archive.get("path") or "")
        path = ROOT / rel
        actual = sha256_file(path)
        if actual != str(archive.get("sha256") or ""):
            raise ValueError("archive SHA mismatch: " + rel)
        records, meta = read_archive(path)
        archive_evidence.append({"path": rel, "sha256": actual, "unique_hands": int(meta["unique_hands"])})
        for record in records:
            old = by_id.get(record.hand_id)
            if old is None or (getattr(old, "language", "") != "en" and record.language == "en"):
                by_id[record.hand_id] = record
    target = set(by_id) - {str(x) for x in excluded.get("hand_ids") or []}
    if len(target) != int(admissible.get("unique_hands") or 0):
        raise ValueError("certified target identity mismatch")
    if fingerprint(target) != str(admissible.get("fingerprint_sha256") or ""):
        raise ValueError("certified target fingerprint mismatch")
    ids = {hid for hid in target if split_for(hid) == split}
    expected = int((admissible.get("split_counts") or {}).get(split) or 0)
    if len(ids) != expected:
        raise ValueError(f"{split} count mismatch")
    return [by_id[x] for x in sorted(ids, key=int)], {
        "split": split,
        "hands": len(ids),
        "hand_ids_fingerprint_sha256": fingerprint(ids),
        "archives": archive_evidence,
    }


def validation_rows() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    records, provenance = load_certified_split("VALIDATION")
    rows: list[dict[str, Any]] = []
    parsed = 0
    for record in records:
        hand = parse_hand(record.text, record.source_file)
        if not hand:
            raise ValueError("VALIDATION hand failed parsing: " + str(record.hand_id))
        parsed += 1
        for row in decision_rows(hand, include_preflop_context_v1=True):
            if row.get("split") != "VALIDATION":
                raise AssertionError("non-VALIDATION row crossed #339 evaluator")
            if (
                row.get("street") == "preflop"
                and not row.get("is_hero")
                and str(row.get("family") or "") in FOCUS_FAMILIES
                and str(row.get("action") or "").upper() != "CHECK"
            ):
                rows.append(row)
    provenance["hands_parsed"] = parsed
    provenance["population_preflop_rows_in_scope"] = len(rows)
    return rows, provenance


def _candidate_index(candidate: Mapping[str, Any]) -> dict[tuple[str, str | None], Mapping[str, Any]]:
    out: dict[tuple[str, str | None], Mapping[str, Any]] = {}
    for node in candidate.get("nodes") or []:
        key = (str(node.get("support_context_key") or ""), node.get("hand_class"))
        if key in out:
            raise ValueError("duplicate candidate support node")
        out[key] = node
    return out


def _normalised_action(action: Any) -> str:
    value = str(action or "").upper()
    return "CALL" if value == "LIMP" else value


def _reference_probability(
    model: Mapping[str, Any],
    index: Mapping[str, list[dict[str, Any]]],
    row: Mapping[str, Any],
    *,
    hand_conditioned: bool,
) -> tuple[float, str, bool]:
    match = find_closest(dict(index), dict(row))
    if not match:
        return EPS, "UNSUPPORTED", False
    node = match["node"]
    original_action = str(row.get("action") or "").upper()
    grid = list(((model.get("hand_grid") or {}).get("classes") or []))
    if hand_conditioned and row.get("known_hand_class"):
        p = policy_probability(node, str(row["known_hand_class"]), original_action, grid)
        source = "POLICY169_HAND"
    else:
        try:
            policy = decode_policy169(node, grid)
            weights = hand_weights(grid, (model.get("hand_grid") or {}).get("meta"))
            p = sum(float(weights[h]) * float((policy.get(h) or {}).get(original_action, 0.0)) for h in weights)
            source = "POLICY169_COMBO_WEIGHTED"
        except (ValueError, TypeError, KeyError):
            p = float(((node.get("population_model") or {}).get("frequencies") or {}).get(original_action, 0.0) or 0.0)
            source = "MARGINAL_FREQUENCY"
    return max(EPS, min(1.0, float(p))), source, bool(match.get("exact"))


def _metric(detail: list[dict[str, Any]], *, samples: int, seed: int) -> dict[str, Any]:
    if not detail:
        return {
            "rows": 0,
            "hands": 0,
            "reference_logloss": None,
            "candidate_logloss": None,
            "delta_candidate_minus_reference": None,
            "affected_rows": 0,
            "paired_bootstrap": bootstrap([], samples=samples, seed=seed),
        }
    ref = sum(float(x["reference_nll"]) for x in detail) / len(detail)
    cand = sum(float(x["candidate_nll"]) for x in detail) / len(detail)
    return {
        "rows": len(detail),
        "hands": len({str(x["hand_id"]) for x in detail}),
        "reference_logloss": ref,
        "candidate_logloss": cand,
        "delta_candidate_minus_reference": cand - ref,
        "affected_rows": sum(abs(float(x["delta_nll"])) > 1e-15 for x in detail),
        "paired_bootstrap": bootstrap(detail, samples=samples, seed=seed),
    }


def evaluate_validation(
    protocol: Mapping[str, Any],
    candidate: Mapping[str, Any],
    fit_evidence: Mapping[str, Any],
) -> dict[str, Any]:
    if sha256_file(REFERENCE) != EXPECTED_REFERENCE_HASH:
        raise ValueError("active Model A v5 reference hash drifted")
    model = json.loads(REFERENCE.read_text(encoding="utf-8"))
    reference_index = by_actor(list(model.get("nodes") or []))
    candidate_index = _candidate_index(candidate)
    rows, validation_provenance = validation_rows()

    primary_detail: list[dict[str, Any]] = []
    hand_detail: list[dict[str, Any]] = []
    unresolved = 0
    reference_fallback = 0
    for row in rows:
        key = support_context_key(row)
        marginal = candidate_index.get((key, None))
        if marginal is None:
            unresolved += 1
            continue
        action = _normalised_action(row.get("action"))
        if action not in ACTIONS:
            continue
        cp = max(EPS, min(1.0, float((marginal.get("probabilities") or {}).get(action, 0.0))))
        rp, rsource, rexact = _reference_probability(model, reference_index, row, hand_conditioned=False)
        if not rexact:
            reference_fallback += 1
        cn, rn = -math.log(cp), -math.log(rp)
        primary_detail.append({
            "hand_id": str(row["hand_id"]),
            "delta_nll": cn - rn,
            "candidate_nll": cn,
            "reference_nll": rn,
            "reference_source": rsource,
        })

        hand_class = row.get("known_hand_class")
        hnode = candidate_index.get((key, str(hand_class))) if hand_class else None
        if hnode is not None:
            hcp = max(EPS, min(1.0, float((hnode.get("probabilities") or {}).get(action, 0.0))))
            hrp, hrsource, _ = _reference_probability(model, reference_index, row, hand_conditioned=True)
            hcn, hrn = -math.log(hcp), -math.log(hrp)
            hand_detail.append({
                "hand_id": str(row["hand_id"]),
                "delta_nll": hcn - hrn,
                "candidate_nll": hcn,
                "reference_nll": hrn,
                "reference_source": hrsource,
            })

    eval_cfg = protocol["evaluation"]
    primary_cfg = eval_cfg["primary"]
    hand_cfg = eval_cfg["required_hand_conditioned"]
    primary = _metric(
        primary_detail,
        samples=int(primary_cfg["bootstrap_samples"]),
        seed=int(primary_cfg["bootstrap_seed"]),
    )
    hand = _metric(
        hand_detail,
        samples=int(hand_cfg["bootstrap_samples"]),
        seed=int(hand_cfg["bootstrap_seed"]),
    )
    primary_gate = (
        primary["rows"] > 0
        and primary["affected_rows"] > 0
        and float(primary["paired_bootstrap"]["ci95"][1]) <= 0.0
    )
    hand_support_gate = (
        int(hand["rows"]) >= int(hand_cfg["minimum_rows"])
        and int(hand["hands"]) >= int(hand_cfg["minimum_hands"])
    )
    hand_gate = (
        hand_support_gate
        and hand["affected_rows"] > 0
        and float(hand["paired_bootstrap"]["ci95"][1]) <= 0.0
    )
    admitted = primary_gate and hand_gate
    result = {
        "schema": "poker-model-a-preflop-sizing-validation/v1",
        "issue": 339,
        "phase": "VALIDATION",
        "selection_split": "VALIDATION",
        "protocol": {
            "path": PROTOCOL.relative_to(ROOT).as_posix(),
            "sha256": sha256_file(PROTOCOL),
            "status": protocol["status"],
        },
        "inputs": {
            "candidate_sha256": fit_evidence["candidate_sha256"],
            "support_report_hash": EXPECTED_SUPPORT_HASH,
            "reference": {
                "path": REFERENCE.relative_to(ROOT).as_posix(),
                "sha256": EXPECTED_REFERENCE_HASH,
            },
            "validation": validation_provenance,
        },
        "coverage": {
            "validation_population_rows_in_scope": len(rows),
            "exact_price_candidate_rows": len(primary_detail),
            "unresolved_no_exact_supported_price_cell": unresolved,
            "reference_runtime_fallback_rows_on_candidate_universe": reference_fallback,
            "hand_conditioned_rows": len(hand_detail),
        },
        "metrics": {
            "all_supported_rows": primary,
            "identifiable_revealed_hand_rows": hand,
        },
        "gate": {
            "primary_ci95_upper_le_zero": primary_gate,
            "hand_support_minimum_met": hand_support_gate,
            "hand_ci95_upper_le_zero": hand_gate,
        },
        "outcome": "ADMIT_FOR_314" if admitted else "RETAIN_ACTIVE_REFERENCE",
        "reason": (
            "both frozen VALIDATION gates passed; candidate may be consumed by #314 but is not promoted"
            if admitted
            else "frozen VALIDATION gate not established; retain active Model A reference"
        ),
        "test_consumed": False,
        "test_authorized": False,
        "production_effect": "NONE",
        "active_model_replaced": False,
        "model_b_consumed": False,
        "hero_ev_consumed": False,
        "ui_modified": False,
        "issue_108_consumed": False,
    }
    result["evidence_sha256"] = canonical_hash(result)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("fit", "validation", "both"), default="both")
    parser.add_argument("--candidate-out", type=Path)
    parser.add_argument("--fit-evidence-out", type=Path)
    parser.add_argument("--validation-out", type=Path)
    parser.add_argument("--print-marker", action="store_true")
    return parser.parse_args()


def write_json(path: Path | None, value: Any) -> None:
    if path is None:
        return
    target = path if path.is_absolute() else ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    protocol = load_protocol()
    _, report = load_support_report()
    candidate, fit_evidence = build_candidate(protocol, report)
    fit_evidence["posterior_321"] = evaluate_kts_posterior(candidate)
    fit_evidence["evidence_sha256"] = canonical_hash(
        {key: value for key, value in fit_evidence.items() if key != "evidence_sha256"}
    )
    write_json(args.candidate_out, candidate)
    write_json(args.fit_evidence_out, fit_evidence)

    validation = None
    if args.phase in {"validation", "both"}:
        validation = evaluate_validation(protocol, candidate, fit_evidence)
        write_json(args.validation_out, validation)

    compact = {
        "fit": fit_evidence,
        "validation": validation,
    }
    if args.print_marker:
        print("ISSUE339_RESULT=" + json.dumps(compact, sort_keys=True, separators=(",", ":")))
    else:
        print(json.dumps(compact, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

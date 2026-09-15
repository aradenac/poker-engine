#!/usr/bin/env python3
"""Reveal-aware latent preflop range inference for independent opponent Model B.

Every TRAIN opponent observation is retained. Eventual revealed cards are labels;
hidden/folded cards remain latent. For a public preflop action signature, hidden
hands are imputed from P(hand class | signature, context) estimated only from
TRAIN revelations and a combinatorial/context prior. If a signature has no
revealed labels (the common case for immediate folds), it is explicitly
non-identifiable and receives the context prior rather than fabricated cards.

This conditional formulation is robust to reveal propensity varying *between*
action signatures under the stated assumption that, within a signature/context,
revelation is not additionally hand-dependent. That remaining MNAR assumption is
not identifiable from HH alone, so 0.0/0.5/1.0 signal sensitivity is exported.

Serialized nodes preserve the legacy ``n``/``counts`` consumer surface.
``counts`` are fractional expected latent counts; ``revealed_counts`` are actual
observed card labels and stay separately auditable.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

from tools.datasets.build_hand_history_increment import HandRecord, split_for
from tools.training.independent_profiles.build_model_b import (
    RANGE_LEVELS,
    combo_class,
    hand_notations,
    key_for,
    parse_hand,
    preflop_summary,
)
from tools.training.independent_profiles.build_player_features import merge_archives

SCHEMA = "independent-preflop-latent-ranges/v1"
AUDIT_SCHEMA = "independent-preflop-reveal-audit/v1"
DEFAULT_SENSITIVITY_POWERS = (0.0, 0.5, 1.0)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def normalized(values: dict[str, float]) -> dict[str, float]:
    total = sum(max(0.0, float(v)) for v in values.values())
    if total <= 0:
        raise ValueError("cannot normalize zero mass")
    return {k: max(0.0, float(v)) / total for k, v in values.items()}


def total_variation(left: dict[str, float], right: dict[str, float]) -> float:
    keys = set(left) | set(right)
    return 0.5 * sum(abs(float(left.get(k, 0.0)) - float(right.get(k, 0.0))) for k in keys)


def geometric_interpolate(
    baseline: dict[str, float], conditioned: dict[str, float], power: float
) -> dict[str, float]:
    if power < 0:
        raise ValueError("decision signal power must be non-negative")
    if power == 0:
        return dict(baseline)
    weights = {}
    for key in baseline:
        base = max(float(baseline[key]), 1e-300)
        cond = max(float(conditioned[key]), 1e-300)
        # baseline * likelihood-ratio**power. power=1 yields conditioned.
        weights[key] = base * ((cond / base) ** power)
    return normalized(weights)


def preflop_signature(hand: dict[str, Any], player: str) -> str:
    labels: list[str] = []
    raises = 0
    for event in hand["events"]["preflop"]:
        typ = event["type"]
        actor = event["player"]
        label: str | None = None
        if typ == "fold":
            label = "FOLD"
        elif typ == "check":
            label = "CHECK"
        elif typ == "call":
            label = "LIMP" if raises == 0 else "CALL"
        elif typ in {"bet", "raise"}:
            label = "RAISE"
        if actor == player and label is not None:
            labels.append(label)
        if typ in {"bet", "raise"}:
            raises += 1
    return ">".join(labels) if labels else "NO_DECISION"


def terminal_role(base_role: str, signature: str) -> str:
    return "FOLDER" if signature.split(">")[-1:] == ["FOLD"] else base_role


def collect_observations(
    records: Iterable[HandRecord],
    player_profile: dict[str, int],
    default_profile: int,
    excluded_players: set[str],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    audit = Counter()
    reveal_by_signature: dict[str, Counter] = defaultdict(Counter)

    for record in records:
        if split_for(record.hand_id) != "TRAIN":
            raise ValueError(f"non-TRAIN record reached latent range fit: {record.hand_id}")
        hand = parse_hand(record)
        if hand is None:
            audit["hands_unparsed"] += 1
            continue
        audit["hands_parsed"] += 1
        pot_type, roles, _, _, _ = preflop_summary(hand)
        for player in hand["players"]:
            if player in excluded_players:
                audit["excluded_player_observations"] += 1
                continue
            signature = preflop_signature(hand, player)
            cards = hand["known_cards"].get(player)
            hand_class = combo_class(cards) if cards else None
            if cards and hand_class is None:
                audit["invalid_known_cards"] += 1
                hand_class = None
            profile = int(player_profile.get(player, default_profile))
            observations.append({
                "hand_id": str(record.hand_id),
                "profile": profile,
                "position": hand["positions"].get(player, "NA"),
                "pot_type": pot_type,
                "preflop_role": terminal_role(roles.get(player, "OTHER"), signature),
                "signature": signature,
                "hand_class": hand_class,
                "profile_source": "TRAIN_KNOWN_PLAYER" if player in player_profile else "TRAIN_COLD_START_PROFILE",
            })
            audit["observations"] += 1
            audit["revealed"] += int(hand_class is not None)
            audit["hidden"] += int(hand_class is None)
            audit["cold_start_profile_observations"] += int(player not in player_profile)
            reveal_by_signature[signature]["total"] += 1
            reveal_by_signature[signature]["revealed"] += int(hand_class is not None)

    signature_rows = {}
    for signature, counts in sorted(reveal_by_signature.items()):
        total = int(counts["total"])
        revealed = int(counts["revealed"])
        signature_rows[signature] = {
            "total": total,
            "revealed": revealed,
            "hidden": total - revealed,
            "reveal_rate": revealed / total if total else None,
            "card_distribution_identifiable_from_revelations": revealed > 0,
        }
    return observations, {"counts": dict(sorted(audit.items())), "reveal_by_signature": signature_rows}


def fit_latent_node(
    observations: list[dict[str, Any]],
    notations: list[str],
    multiplicity: dict[str, int],
    *,
    prior_strength: float = 50.0,
    action_prior_strength: float = 20.0,
    decision_signal_power: float = 1.0,
    max_iterations: int = 100,
    tolerance: float = 1e-10,
) -> dict[str, Any]:
    """Estimate expected class counts with signature-stratified latent imputation.

    ``max_iterations``/``tolerance`` remain accepted for API stability but are not
    used: conditional imputation has a closed-form single E-step.
    """
    del max_iterations, tolerance
    if not observations:
        raise ValueError("latent node requires observations")
    if prior_strength < 0 or action_prior_strength <= 0 or decision_signal_power < 0:
        raise ValueError("invalid latent range hyperparameters")

    combo_prior = normalized({h: float(multiplicity[h]) for h in notations})
    revealed_counts = Counter(
        str(o["hand_class"]) for o in observations if o.get("hand_class") in combo_prior
    )
    revealed_n = sum(revealed_counts.values())
    n = len(observations)
    hidden_by_signature = Counter(
        str(o["signature"]) for o in observations if o.get("hand_class") not in combo_prior
    )
    revealed_by_signature_hand: dict[str, Counter] = defaultdict(Counter)
    revealed_by_signature = Counter()
    all_by_signature = Counter(str(o["signature"]) for o in observations)
    for observation in observations:
        hand_class = observation.get("hand_class")
        if hand_class in combo_prior:
            signature = str(observation["signature"])
            revealed_by_signature_hand[signature][str(hand_class)] += 1
            revealed_by_signature[signature] += 1

    # Context distribution is the fallback when a signature has no card labels.
    context_prior = normalized({
        h: float(revealed_counts[h]) + prior_strength * combo_prior[h] for h in notations
    })
    expected_counts = {h: float(revealed_counts[h]) for h in notations}
    nonidentified: list[str] = []

    for signature, hidden_count in hidden_by_signature.items():
        labelled = int(revealed_by_signature[signature])
        if labelled == 0:
            conditioned = dict(context_prior)
            nonidentified.append(signature)
        else:
            signature_counts = revealed_by_signature_hand[signature]
            conditioned = normalized({
                h: float(signature_counts[h]) + action_prior_strength * context_prior[h]
                for h in notations
            })
        posterior = geometric_interpolate(context_prior, conditioned, decision_signal_power)
        for h, probability in posterior.items():
            expected_counts[h] += hidden_count * probability

    if not math.isclose(sum(expected_counts.values()), n, rel_tol=0.0, abs_tol=1e-6):
        raise AssertionError((sum(expected_counts.values()), n))

    return {
        "n": n,
        "counts": {h: round(expected_counts[h], 8) for h in notations if expected_counts[h] > 1e-10},
        "revealed_n": revealed_n,
        "hidden_n": n - revealed_n,
        "reveal_rate": revealed_n / n,
        "revealed_counts": dict(sorted(revealed_counts.items())),
        "identification": "FULLY_OBSERVED" if revealed_n == n else "NO_CARD_LABELS" if revealed_n == 0 else "PARTIAL_MISSING_NOT_AT_RANDOM",
        "partial_identification_width": (n - revealed_n) / n,
        "nonidentified_signatures": sorted(nonidentified),
        "signature_support": {
            signature: {"n": int(all_by_signature[signature]), "revealed_n": int(revealed_by_signature[signature])}
            for signature in sorted(all_by_signature)
        },
        "fit": {
            "method": "signature_conditioned_closed_form_imputation",
            "prior_strength": prior_strength,
            "signature_hand_prior_strength": action_prior_strength,
            "decision_signal_power": decision_signal_power,
            "assumption": "within a public signature/context, eventual revelation is not additionally hand-dependent",
        },
    }


def _distribution(node: dict[str, Any], notations: list[str]) -> dict[str, float]:
    n = float(node["n"])
    return {h: float(node["counts"].get(h, 0.0)) / n for h in notations}


def build_latent_ranges(
    observations: list[dict[str, Any]],
    *,
    backoff_min_observations: int = 20,
    prior_strength: float = 50.0,
    action_prior_strength: float = 20.0,
    sensitivity_powers: tuple[float, ...] = DEFAULT_SENSITIVITY_POWERS,
) -> tuple[dict[str, Any], dict[str, Any]]:
    notations, multiplicity = hand_notations()
    levels_out: list[dict[str, Any]] = []
    sensitivity_summary: list[dict[str, Any]] = []

    for level_index, cols in enumerate(RANGE_LEVELS):
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for observation in observations:
            groups[key_for(cols, observation)].append(observation)
        serialized: dict[str, Any] = {}
        alternate = [p for p in sensitivity_powers if p != 1.0]
        weighted_tv = {str(p): 0.0 for p in alternate}
        max_tv = {str(p): 0.0 for p in alternate}
        kept_weight = 0
        for key in sorted(groups):
            rows = groups[key]
            if level_index != len(RANGE_LEVELS) - 1 and len(rows) < backoff_min_observations:
                continue
            nominal = fit_latent_node(
                rows, notations, multiplicity,
                prior_strength=prior_strength,
                action_prior_strength=action_prior_strength,
                decision_signal_power=1.0,
            )
            nominal_dist = _distribution(nominal, notations)
            node_sensitivity = {}
            for power in alternate:
                variant = fit_latent_node(
                    rows, notations, multiplicity,
                    prior_strength=prior_strength,
                    action_prior_strength=action_prior_strength,
                    decision_signal_power=power,
                )
                tv = total_variation(nominal_dist, _distribution(variant, notations))
                node_sensitivity[str(power)] = round(tv, 8)
                weighted_tv[str(power)] += tv * len(rows)
                max_tv[str(power)] = max(max_tv[str(power)], tv)
            nominal["sensitivity_total_variation_from_nominal"] = node_sensitivity
            serialized[key] = nominal
            kept_weight += len(rows)
        levels_out.append({"cols": cols, "data": serialized})
        sensitivity_summary.append({
            "level": level_index,
            "cols": cols,
            "nodes": len(serialized),
            "weighted_mean_total_variation": {
                p: weighted_tv[p] / kept_weight if kept_weight else None for p in weighted_tv
            },
            "max_total_variation": max_tv,
        })

    return {
        "schema": SCHEMA,
        "semantics": "expected latent hand-class counts from TRAIN public decisions plus eventual revelations; hidden cards remain latent",
        "context_columns": RANGE_LEVELS,
        "notations": notations,
        "multiplicity": multiplicity,
        "backoff_min_observations": backoff_min_observations,
        "fit": {
            "split": "TRAIN",
            "prior": "combinatorial 1326-combo prior shrunk by context revelations",
            "prior_strength": prior_strength,
            "signature_conditioning": "P(hand|public preflop signature, context) from revealed TRAIN hands",
            "signature_hand_prior_strength": action_prior_strength,
            "nominal_decision_signal_power": 1.0,
            "sensitivity_decision_signal_powers": list(sensitivity_powers),
            "missing_cards": "never labelled; fractional posterior mass only",
            "future_information_runtime_rule": "eventual revelations are aggregate TRAIN labels only and never exposed to a runtime decision before revelation",
        },
        "levels": levels_out,
    }, {
        "schema": "independent-preflop-reveal-sensitivity/v1",
        "interpretation": "Variation across signature-signal powers measures dependence on an untestable missing-card extrapolation; it is not a confidence interval.",
        "levels": sensitivity_summary,
    }


def certified_records(
    archives: list[Path], stakes: set[str], certification_path: Path
) -> tuple[list[HandRecord], dict[str, Any]]:
    certification = json.loads(certification_path.read_text(encoding="utf-8"))
    by_id, source_provenance = merge_archives(archives, stakes)
    excluded_ids = set(str(x) for x in certification["status"]["EXCLUDED"].get("hand_ids", []))
    retained = {str(hid): record for hid, record in by_id.items() if str(hid) not in excluded_ids}
    expected = int(certification["status"]["ADMISSIBLE"]["unique_hands"])
    if len(retained) != expected:
        raise ValueError(f"certified population mismatch: retained {len(retained)}, expected {expected}; provide every certification archive")
    split_counts = Counter(split_for(hid) for hid in retained)
    expected_splits = certification["status"]["ADMISSIBLE"]["split_counts"]
    if dict(split_counts) != expected_splits:
        raise ValueError(("certified split mismatch", dict(split_counts), expected_splits))
    return list(retained.values()), {
        "certification": certification_path.as_posix(),
        "certification_sha256": sha256_file(certification_path),
        "population_fingerprint_sha256": certification["status"]["ADMISSIBLE"]["fingerprint_sha256"],
        "unique_hands": expected,
        "split_counts": expected_splits,
        "source": source_provenance,
    }


def build_from_records(
    records: list[HandRecord],
    profiles: dict[str, Any],
    excluded_players: set[str],
    **fit_kwargs: Any,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    train_records = [record for record in records if split_for(record.hand_id) == "TRAIN"]
    player_profile = {str(k): int(v) for k, v in profiles["player_profile"].items()}
    default_profile = int(max(profiles["profiles"], key=lambda p: p["appearance_weight"])["profile"])
    observations, audit = collect_observations(train_records, player_profile, default_profile, excluded_players)
    ranges, sensitivity = build_latent_ranges(observations, **fit_kwargs)
    return ranges, sensitivity, {
        "schema": AUDIT_SCHEMA,
        "fit_split": "TRAIN",
        "train_hands": len(train_records),
        "excluded_players": sorted(excluded_players),
        "known_player_profiles": len(player_profile),
        "cold_start_profile": default_profile,
        "observation_audit": audit,
        "identification_limits": [
            "Preflop folds normally have no revealed hole cards; a signature with zero labels is non-identifiable and stays on the context prior.",
            "The nominal imputation assumes revelation is not additionally hand-dependent after conditioning on public signature/context; HH alone cannot verify that MNAR assumption.",
            "Sensitivity powers expose dependence on signature conditioning but are not statistical confidence bounds.",
            "Aggregate TRAIN revelations may fit parameters, but runtime decisions must never receive cards before their actual revelation event.",
        ],
    }

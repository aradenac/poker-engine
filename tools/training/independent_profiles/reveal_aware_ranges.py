#!/usr/bin/env python3
"""Reveal-aware latent preflop range inference for independent opponent Model B.

The historical Model-B range table counted only known cards from players still
active after preflop.  This module keeps *every* opponent preflop observation,
while preserving the distinction between observed and latent hole cards.

Important statistical contract:
- only TRAIN observations are allowed to fit a candidate;
- Model A outputs (EV, recommendation, policy, pseudo-labels) are never inputs;
- a hidden/folded hand is never promoted to a known card label;
- hidden hands receive fractional posterior mass only when TRAIN revelations
  identify a hand/action association; otherwise they remain prior-driven;
- sensitivity to the hand/action signal is reported instead of pretending the
  missing-card mechanism is identifiable from PokerStars HH alone.

The serialized nodes keep the legacy ``n``/``counts`` surface, so the existing
Model-B range probability consumer can score a candidate without a second
prediction implementation.  ``counts`` are expected latent counts, not observed
card counts; ``revealed_counts`` and identification metadata preserve that fact.
"""
from __future__ import annotations

import argparse
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


def preflop_signature(hand: dict[str, Any], player: str) -> str:
    """Return the actor's observable preflop action sequence.

    Posts are excluded.  CALL before any raise is labelled LIMP; later calls are
    CALL.  The signature is computed from the public action stream and therefore
    contains no future cards.
    """
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
    # Folds must remain represented in the behavioural population.  Extending the
    # role value does not change the RANGE_LEVELS context columns.
    if signature.split(">")[-1:] == ["FOLD"]:
        return "FOLDER"
    return base_role


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
            role = terminal_role(roles.get(player, "OTHER"), signature)
            observation = {
                "hand_id": str(record.hand_id),
                "profile": profile,
                "position": hand["positions"].get(player, "NA"),
                "pot_type": pot_type,
                "preflop_role": role,
                "signature": signature,
                "hand_class": hand_class,
                "profile_source": "TRAIN_KNOWN_PLAYER" if player in player_profile else "TRAIN_COLD_START_PROFILE",
            }
            observations.append(observation)
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
            "card_action_link_identifiable": revealed > 0,
        }
    return observations, {
        "counts": dict(sorted(audit.items())),
        "reveal_by_signature": signature_rows,
    }


def _action_likelihoods(
    observations: list[dict[str, Any]],
    notations: list[str],
    action_prior_strength: float,
) -> tuple[dict[str, dict[str, float]], set[str]]:
    signatures = sorted({str(o["signature"]) for o in observations})
    signature_counts = Counter(str(o["signature"]) for o in observations)
    sig_prior = normalized({s: float(signature_counts[s]) + 1.0 for s in signatures})
    known_by_hand: dict[str, Counter] = {h: Counter() for h in notations}
    known_signature_totals = Counter()
    for obs in observations:
        hand_class = obs.get("hand_class")
        if hand_class in known_by_hand:
            signature = str(obs["signature"])
            known_by_hand[hand_class][signature] += 1
            known_signature_totals[signature] += 1

    likelihoods: dict[str, dict[str, float]] = {}
    for hand_class in notations:
        counts = known_by_hand[hand_class]
        n = sum(counts.values())
        likelihoods[hand_class] = {
            signature: (
                float(counts[signature]) + action_prior_strength * sig_prior[signature]
            ) / (float(n) + action_prior_strength)
            for signature in signatures
        }
    nonidentified = {s for s in signatures if known_signature_totals[s] == 0}
    return likelihoods, nonidentified


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
    """Fit expected hand-class counts without inventing labels for hidden hands."""
    if not observations:
        raise ValueError("latent node requires observations")
    if prior_strength < 0 or action_prior_strength <= 0 or decision_signal_power < 0:
        raise ValueError("invalid latent range hyperparameters")

    combo_prior = normalized({h: float(multiplicity[h]) for h in notations})
    revealed_counts = Counter(
        str(o["hand_class"]) for o in observations if o.get("hand_class") in combo_prior
    )
    hidden = [o for o in observations if o.get("hand_class") not in combo_prior]
    revealed_n = sum(revealed_counts.values())
    n = len(observations)
    likelihoods, nonidentified = _action_likelihoods(observations, notations, action_prior_strength)

    current = normalized({
        h: float(revealed_counts[h]) + prior_strength * combo_prior[h]
        for h in notations
    })
    expected_counts: dict[str, float] = {h: float(revealed_counts[h]) for h in notations}
    final_delta = math.inf
    iterations = 0

    for iterations in range(1, max_iterations + 1):
        expected_counts = {h: float(revealed_counts[h]) for h in notations}
        for obs in hidden:
            signature = str(obs["signature"])
            weights = {
                h: current[h] * (likelihoods[h][signature] ** decision_signal_power)
                for h in notations
            }
            posterior = normalized(weights)
            for h, p in posterior.items():
                expected_counts[h] += p
        updated = normalized({
            h: expected_counts[h] + prior_strength * combo_prior[h]
            for h in notations
        })
        final_delta = max(abs(updated[h] - current[h]) for h in notations)
        current = updated
        if final_delta <= tolerance:
            break

    # Compatibility counts must sum to the actual observations, not to the
    # Dirichlet pseudo-counts used for stabilization.
    count_total = sum(expected_counts.values())
    if not math.isclose(count_total, n, rel_tol=0.0, abs_tol=1e-6):
        raise AssertionError((count_total, n))

    revealed_by_signature = Counter(
        str(o["signature"]) for o in observations if o.get("hand_class") in combo_prior
    )
    all_by_signature = Counter(str(o["signature"]) for o in observations)
    return {
        "n": n,
        "counts": {h: round(expected_counts[h], 8) for h in notations if expected_counts[h] > 1e-10},
        "revealed_n": revealed_n,
        "hidden_n": n - revealed_n,
        "reveal_rate": revealed_n / n,
        "revealed_counts": dict(sorted(revealed_counts.items())),
        "identification": (
            "FULLY_OBSERVED" if revealed_n == n else "NO_CARD_LABELS" if revealed_n == 0 else "PARTIAL_MISSING_NOT_AT_RANDOM"
        ),
        "partial_identification_width": (n - revealed_n) / n,
        "nonidentified_signatures": sorted(nonidentified),
        "signature_support": {
            s: {
                "n": int(all_by_signature[s]),
                "revealed_n": int(revealed_by_signature[s]),
            }
            for s in sorted(all_by_signature)
        },
        "fit": {
            "iterations": iterations,
            "max_probability_delta": final_delta,
            "prior_strength": prior_strength,
            "action_prior_strength": action_prior_strength,
            "decision_signal_power": decision_signal_power,
        },
    }


def _node_distribution(node: dict[str, Any], notations: list[str]) -> dict[str, float]:
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
        for obs in observations:
            groups[key_for(cols, obs)].append(obs)
        serialized = {}
        weighted_tv = {str(power): 0.0 for power in sensitivity_powers if power != 1.0}
        max_tv = {str(power): 0.0 for power in sensitivity_powers if power != 1.0}
        kept_weight = 0
        for key in sorted(groups):
            rows = groups[key]
            if level_index != len(RANGE_LEVELS) - 1 and len(rows) < backoff_min_observations:
                continue
            nominal = fit_latent_node(
                rows,
                notations,
                multiplicity,
                prior_strength=prior_strength,
                action_prior_strength=action_prior_strength,
                decision_signal_power=1.0,
            )
            nominal_dist = _node_distribution(nominal, notations)
            node_sensitivity = {}
            for power in sensitivity_powers:
                if power == 1.0:
                    continue
                variant = fit_latent_node(
                    rows,
                    notations,
                    multiplicity,
                    prior_strength=prior_strength,
                    action_prior_strength=action_prior_strength,
                    decision_signal_power=power,
                )
                tv = total_variation(nominal_dist, _node_distribution(variant, notations))
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
                p: (weighted_tv[p] / kept_weight if kept_weight else None) for p in weighted_tv
            },
            "max_total_variation": max_tv,
        })

    ranges = {
        "schema": SCHEMA,
        "semantics": "expected latent hand-class counts from TRAIN public decisions plus eventual revelations; hidden cards remain latent",
        "context_columns": RANGE_LEVELS,
        "notations": notations,
        "multiplicity": multiplicity,
        "backoff_min_observations": backoff_min_observations,
        "fit": {
            "split": "TRAIN",
            "prior": "combinatorial 1326-combo prior",
            "prior_strength": prior_strength,
            "action_likelihood": "revealed TRAIN hand/action association shrunk to all-observation action marginal",
            "action_prior_strength": action_prior_strength,
            "nominal_decision_signal_power": 1.0,
            "sensitivity_decision_signal_powers": list(sensitivity_powers),
            "missing_cards": "never labelled; fractional posterior mass only",
            "future_information_runtime_rule": "eventual revelations are aggregate TRAIN labels only and are never exposed to a runtime decision before revelation",
        },
        "levels": levels_out,
    }
    sensitivity = {
        "schema": "independent-preflop-reveal-sensitivity/v1",
        "interpretation": "Variation across decision-signal powers measures dependence on the non-identifiable hand/action extrapolation for hidden cards; it is not a frequentist confidence interval.",
        "levels": sensitivity_summary,
    }
    return ranges, sensitivity


def certified_records(
    archives: list[Path],
    stakes: set[str],
    certification_path: Path,
) -> tuple[list[HandRecord], dict[str, Any]]:
    certification = json.loads(certification_path.read_text(encoding="utf-8"))
    by_id, source_provenance = merge_archives(archives, stakes)
    excluded_ids = set(str(x) for x in certification["status"]["EXCLUDED"].get("hand_ids", []))
    retained = {str(hid): record for hid, record in by_id.items() if str(hid) not in excluded_ids}
    expected = int(certification["status"]["ADMISSIBLE"]["unique_hands"])
    if len(retained) != expected:
        raise ValueError(
            f"certified population mismatch: retained {len(retained)} hands, certification expects {expected}; provide all certification archives"
        )
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
    train_records = [r for r in records if split_for(r.hand_id) == "TRAIN"]
    player_profile = {str(k): int(v) for k, v in profiles["player_profile"].items()}
    default_profile = int(max(profiles["profiles"], key=lambda p: p["appearance_weight"])["profile"])
    observations, audit = collect_observations(
        train_records, player_profile, default_profile, excluded_players
    )
    ranges, sensitivity = build_latent_ranges(observations, **fit_kwargs)
    audit_doc = {
        "schema": AUDIT_SCHEMA,
        "fit_split": "TRAIN",
        "train_hands": len(train_records),
        "excluded_players": sorted(excluded_players),
        "known_player_profiles": len(player_profile),
        "cold_start_profile": default_profile,
        "observation_audit": audit,
        "identification_limits": [
            "Preflop folds normally have no revealed hole cards; where a signature has no revealed labels its hand composition is not identified and stays prior-driven.",
            "Eventual showdown/muck revelations can be selection-biased by postflop survival and strength; sensitivity variants quantify dependence on action-signal extrapolation but cannot identify the true missing-card mechanism.",
            "Aggregate TRAIN revelations may fit parameters, but runtime decisions must never receive cards before their actual revelation event.",
        ],
    }
    return ranges, sensitivity, audit_doc


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profiles", type=Path, required=True)
    parser.add_argument("--archive", type=Path, action="append", required=True)
    parser.add_argument("--certification", type=Path, required=True)
    parser.add_argument("--stake", action="append", default=["100/200"])
    parser.add_argument("--exclude-player", action="append", default=[])
    parser.add_argument("--backoff-min-observations", type=int, default=20)
    parser.add_argument("--prior-strength", type=float, default=50.0)
    parser.add_argument("--action-prior-strength", type=float, default=20.0)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sensitivity-output", type=Path, required=True)
    parser.add_argument("--audit-output", type=Path, required=True)
    args = parser.parse_args()

    profiles = json.loads(args.profiles.read_text(encoding="utf-8"))
    records, population = certified_records(args.archive, set(args.stake), args.certification)
    ranges, sensitivity, audit = build_from_records(
        records,
        profiles,
        set(args.exclude_player),
        backoff_min_observations=args.backoff_min_observations,
        prior_strength=args.prior_strength,
        action_prior_strength=args.action_prior_strength,
    )
    for document in (ranges, sensitivity, audit):
        document["population"] = population
        document["profiles_sha256"] = sha256_file(args.profiles)

    for path, document in (
        (args.output, ranges),
        (args.sensitivity_output, sensitivity),
        (args.audit_output, audit),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({
        "schema": SCHEMA,
        "population": population,
        "fit": ranges["fit"],
        "audit": audit["observation_audit"],
        "sensitivity": sensitivity["levels"],
        "outputs": {
            "ranges": {"path": args.output.as_posix(), "sha256": sha256_file(args.output)},
            "sensitivity": {"path": args.sensitivity_output.as_posix(), "sha256": sha256_file(args.sensitivity_output)},
            "audit": {"path": args.audit_output.as_posix(), "sha256": sha256_file(args.audit_output)},
        },
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

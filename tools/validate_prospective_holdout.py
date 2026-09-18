#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROTOCOL_SCHEMA = "poker-prospective-holdout-protocol/v1"
MANIFEST_SCHEMA = "poker-prospective-holdout/v1"
REPORT_SCHEMA = "poker-prospective-holdout-report/v1"
STATES = ["UNCONSUMED", "EVALUATING", "CLOSED", "RELEASED_TO_FUTURE_TRAIN"]
STATE_RANK = {state: index for index, state in enumerate(STATES)}
CLASSIFICATION_VALUES = {"PASS", "WARN", "FAIL", "INCONCLUSIVE", "NOT_EVALUATED"}
SHA256_LEN = 64
SHA1_LEN = 40


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _is_hex(value: Any, length: int) -> bool:
    if not isinstance(value, str) or len(value) != length:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def _parse_utc(value: Any, field: str, errors: list[str]) -> datetime | None:
    if not isinstance(value, str) or not value:
        errors.append(f"{field}: expected a non-empty UTC timestamp")
        return None
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        errors.append(f"{field}: invalid ISO-8601 timestamp {value!r}")
        return None
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        errors.append(f"{field}: timestamp must be UTC")
        return None
    return parsed.astimezone(timezone.utc)


def _require_sha256(value: Any, field: str, errors: list[str]) -> None:
    if not _is_hex(value, SHA256_LEN):
        errors.append(f"{field}: expected a 64-character SHA-256 hex digest")


def _require_commit_sha(value: Any, field: str, errors: list[str]) -> None:
    if not (_is_hex(value, SHA1_LEN) or _is_hex(value, SHA256_LEN)):
        errors.append(f"{field}: expected a 40- or 64-character commit hash")


def validate_protocol(protocol: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if protocol.get("schema") != PROTOCOL_SCHEMA:
        errors.append(f"protocol.schema must be {PROTOCOL_SCHEMA!r}")
    if protocol.get("manifest_schema") != MANIFEST_SCHEMA:
        errors.append(f"protocol.manifest_schema must be {MANIFEST_SCHEMA!r}")
    if protocol.get("state_order") != STATES:
        errors.append("protocol.state_order must match the canonical prospective state order")
    rules = protocol.get("rules")
    if not isinstance(rules, dict):
        errors.append("protocol.rules must be an object")
        return errors
    for name in (
        "candidate_frozen_before_admission",
        "candidate_fit_identity_frozen",
        "prospective_hands_must_be_absent_from_candidate_fit",
        "append_only_hands_while_unconsumed",
        "ledger_frozen_during_evaluation",
        "no_train_before_closed",
        "thresholds_frozen_before_admission",
        "future_train_requires_new_cycle",
        "separate_drift_coverage_performance_report",
    ):
        if rules.get(name) is not True:
            errors.append(f"protocol.rules.{name} must be true")
    return errors


def validate_manifest(manifest: dict[str, Any], protocol: dict[str, Any]) -> dict[str, Any]:
    errors = validate_protocol(protocol)
    warnings: list[str] = []

    if manifest.get("schema") != MANIFEST_SCHEMA:
        errors.append(f"schema must be {MANIFEST_SCHEMA!r}")
    state = manifest.get("state")
    if state not in STATE_RANK:
        errors.append(f"state must be one of {STATES!r}")

    holdout_id = manifest.get("holdout_id")
    if not isinstance(holdout_id, str) or not holdout_id.strip():
        errors.append("holdout_id must be a non-empty string")

    generation = manifest.get("generation")
    if not isinstance(generation, int) or isinstance(generation, bool) or generation < 1:
        errors.append("generation must be an integer >= 1")
    parent = manifest.get("parent_holdout_id")
    if generation == 1 and parent is not None:
        errors.append("generation 1 must have parent_holdout_id=null")
    if isinstance(generation, int) and generation > 1 and (not isinstance(parent, str) or not parent.strip()):
        errors.append("generation > 1 requires a non-empty parent_holdout_id")

    if not isinstance(manifest.get("population_id"), str) or not manifest.get("population_id", "").strip():
        errors.append("population_id must be a non-empty string")

    precommit = manifest.get("precommit")
    frozen_at = fit_completed_at = None
    if not isinstance(precommit, dict):
        errors.append("precommit must be an object")
        precommit = {}
    else:
        frozen_at = _parse_utc(precommit.get("frozen_at"), "precommit.frozen_at", errors)
        _require_commit_sha(precommit.get("source_commit_sha"), "precommit.source_commit_sha", errors)
        for field in ("prior_hand_ids_sha256", "strategy_sha256", "protocol_sha256", "metrics_sha256", "thresholds_sha256"):
            _require_sha256(precommit.get(field), f"precommit.{field}", errors)
        if precommit.get("protocol_sha256") != canonical_sha256(protocol):
            errors.append("precommit.protocol_sha256 does not match the versioned protocol")

        fit = precommit.get("fit")
        if not isinstance(fit, dict):
            errors.append("precommit.fit must be an object")
            fit = {}
        else:
            fit_completed_at = _parse_utc(fit.get("completed_at"), "precommit.fit.completed_at", errors)
            _require_sha256(fit.get("training_dataset_sha256"), "precommit.fit.training_dataset_sha256", errors)
            _require_sha256(fit.get("training_hand_ids_sha256"), "precommit.fit.training_hand_ids_sha256", errors)

        candidate = precommit.get("candidate")
        if not isinstance(candidate, dict):
            errors.append("precommit.candidate must be an object")
        else:
            if not isinstance(candidate.get("id"), str) or not candidate.get("id", "").strip():
                errors.append("precommit.candidate.id must be a non-empty string")
            _require_sha256(candidate.get("artifact_sha256"), "precommit.candidate.artifact_sha256", errors)
            _require_sha256(candidate.get("pack_sha256"), "precommit.candidate.pack_sha256", errors)

        models = precommit.get("models")
        if not isinstance(models, dict) or not models:
            errors.append("precommit.models must be a non-empty object")
        else:
            for name, digest in sorted(models.items()):
                _require_sha256(digest, f"precommit.models.{name}", errors)

    boundary = manifest.get("temporal_boundary")
    cutoff = admission = None
    if not isinstance(boundary, dict):
        errors.append("temporal_boundary must be an object")
        boundary = {}
    else:
        cutoff = _parse_utc(boundary.get("cutoff_utc"), "temporal_boundary.cutoff_utc", errors)
        admission = _parse_utc(boundary.get("admission_not_before_utc"), "temporal_boundary.admission_not_before_utc", errors)
        if fit_completed_at and frozen_at and fit_completed_at > frozen_at:
            errors.append("precommit.fit.completed_at must be <= precommit.frozen_at")
        if frozen_at and cutoff and frozen_at > cutoff:
            errors.append("precommit.frozen_at must be <= temporal_boundary.cutoff_utc")
        if cutoff and admission and admission <= cutoff:
            errors.append("admission_not_before_utc must be strictly after cutoff_utc")

    hands = manifest.get("hands")
    if not isinstance(hands, list):
        errors.append("hands must be a list")
        hands = []

    seen_ids: set[str] = set()
    seen_hashes: set[str] = set()
    latest_first_seen = None
    for index, hand in enumerate(hands):
        prefix = f"hands[{index}]"
        if not isinstance(hand, dict):
            errors.append(f"{prefix}: expected an object")
            continue

        hand_id = hand.get("hand_id")
        if not isinstance(hand_id, str) or not hand_id:
            errors.append(f"{prefix}.hand_id must be a non-empty string")
        elif hand_id in seen_ids:
            errors.append(f"{prefix}.hand_id duplicates {hand_id!r}")
        else:
            seen_ids.add(hand_id)

        digest = hand.get("sha256")
        _require_sha256(digest, f"{prefix}.sha256", errors)
        if isinstance(digest, str) and digest in seen_hashes:
            errors.append(f"{prefix}.sha256 duplicates a previous hand payload")
        elif isinstance(digest, str):
            seen_hashes.add(digest)

        observed = _parse_utc(hand.get("observed_at"), f"{prefix}.observed_at", errors)
        first_seen = _parse_utc(hand.get("first_seen_at"), f"{prefix}.first_seen_at", errors)
        if admission and observed and observed < admission:
            errors.append(f"{prefix}.observed_at precedes the frozen admission boundary")
        if admission and first_seen and first_seen < admission:
            errors.append(f"{prefix}.first_seen_at precedes the frozen admission boundary")
        if observed and first_seen and first_seen < observed:
            errors.append(f"{prefix}.first_seen_at cannot precede observed_at")
        if first_seen and (latest_first_seen is None or first_seen > latest_first_seen):
            latest_first_seen = first_seen

        novelty = hand.get("novelty_proof")
        if not isinstance(novelty, dict):
            errors.append(f"{prefix}.novelty_proof must be an object")
        else:
            if novelty.get("checked_against_hand_ids_sha256") != precommit.get("prior_hand_ids_sha256"):
                errors.append(f"{prefix}.novelty_proof does not bind to the frozen prior hand-ID universe")
            if novelty.get("absent_from_prior_hand_ids") is not True:
                errors.append(f"{prefix}.novelty_proof.absent_from_prior_hand_ids must be true")
            fit = precommit.get("fit") if isinstance(precommit.get("fit"), dict) else {}
            if novelty.get("checked_against_candidate_fit_hand_ids_sha256") != fit.get("training_hand_ids_sha256"):
                errors.append(f"{prefix}.novelty_proof does not bind to the candidate fit hand-ID fingerprint")
            if novelty.get("absent_from_candidate_fit_hand_ids") is not True:
                errors.append(f"{prefix}.novelty_proof.absent_from_candidate_fit_hand_ids must be true")
            _require_sha256(novelty.get("evidence_sha256"), f"{prefix}.novelty_proof.evidence_sha256", errors)

        train_eligible = hand.get("train_eligible")
        if state == "RELEASED_TO_FUTURE_TRAIN":
            if train_eligible is not True:
                errors.append(f"{prefix}.train_eligible must be true after release")
        elif train_eligible is not False:
            errors.append(f"{prefix}.train_eligible must be false before release")

    previous_sha = manifest.get("previous_manifest_sha256")
    if previous_sha is not None and not _is_hex(previous_sha, SHA256_LEN):
        errors.append("previous_manifest_sha256 must be null or a SHA-256 digest")

    evaluation = manifest.get("evaluation")
    if state == "UNCONSUMED":
        if evaluation is not None:
            errors.append("UNCONSUMED manifest must have evaluation=null")
    elif state == "EVALUATING":
        if not hands:
            errors.append("EVALUATING requires at least one admitted hand")
        if not isinstance(evaluation, dict):
            errors.append("EVALUATING requires an evaluation object")
        else:
            started_at = _parse_utc(evaluation.get("started_at"), "evaluation.started_at", errors)
            if evaluation.get("closed_at") is not None or evaluation.get("report") is not None:
                errors.append("EVALUATING cannot contain closed_at or report")
            if latest_first_seen and started_at and started_at < latest_first_seen:
                errors.append("evaluation.started_at must be on/after every admitted first_seen_at")
    elif state in {"CLOSED", "RELEASED_TO_FUTURE_TRAIN"}:
        if not hands:
            errors.append(f"{state} requires at least one admitted hand")
        if not isinstance(evaluation, dict):
            errors.append(f"{state} requires an evaluation object")
        else:
            started_at = _parse_utc(evaluation.get("started_at"), "evaluation.started_at", errors)
            closed_at = _parse_utc(evaluation.get("closed_at"), "evaluation.closed_at", errors)
            if started_at and closed_at and closed_at < started_at:
                errors.append("evaluation.closed_at cannot precede evaluation.started_at")
            if latest_first_seen and started_at and started_at < latest_first_seen:
                errors.append("evaluation.started_at must be on/after every admitted first_seen_at")
            report = evaluation.get("report")
            if not isinstance(report, dict):
                errors.append("closed evaluation requires report")
            else:
                _require_sha256(report.get("sha256"), "evaluation.report.sha256", errors)
                classification = report.get("classification")
                if not isinstance(classification, dict):
                    errors.append("evaluation.report.classification must be an object")
                else:
                    expected = {"population_drift", "coverage", "performance"}
                    missing = expected.difference(classification)
                    extra = set(classification).difference(expected)
                    if missing:
                        errors.append("evaluation.report.classification missing: " + ", ".join(sorted(missing)))
                    if extra:
                        errors.append("evaluation.report.classification contains unsupported keys: " + ", ".join(sorted(extra)))
                    for key in sorted(expected.intersection(classification)):
                        if classification[key] not in CLASSIFICATION_VALUES:
                            errors.append(
                                f"evaluation.report.classification.{key} must be one of "
                                f"{sorted(CLASSIFICATION_VALUES)!r}"
                            )

    transition = manifest.get("training_transition")
    if state == "RELEASED_TO_FUTURE_TRAIN":
        if not isinstance(transition, dict):
            errors.append("RELEASED_TO_FUTURE_TRAIN requires training_transition")
        else:
            released_at = _parse_utc(transition.get("released_at"), "training_transition.released_at", errors)
            next_cycle = transition.get("next_training_cycle_id")
            if not isinstance(next_cycle, str) or not next_cycle.strip():
                errors.append("training_transition.next_training_cycle_id must be non-empty")
            if isinstance(evaluation, dict):
                closed_at = _parse_utc(evaluation.get("closed_at"), "evaluation.closed_at", [])
                if released_at and closed_at and released_at < closed_at:
                    errors.append("training_transition.released_at cannot precede evaluation.closed_at")
    elif transition is not None:
        errors.append(f"{state}: training_transition must be null before release")

    return {
        "schema": REPORT_SCHEMA,
        "status": "FAIL" if errors else ("WARN" if warnings else "PASS"),
        "errors": errors,
        "warnings": warnings,
        "holdout_id": holdout_id,
        "state": state,
        "hand_count": len(hands),
        "manifest_sha256": canonical_sha256(manifest),
    }


def validate_transition(previous: dict[str, Any], current: dict[str, Any], protocol: dict[str, Any]) -> dict[str, Any]:
    current_report = validate_manifest(current, protocol)
    errors = list(current_report["errors"])
    warnings = list(current_report["warnings"])

    previous_report = validate_manifest(previous, protocol)
    if previous_report["errors"]:
        errors.append("previous manifest is invalid")
        errors.extend(f"previous: {item}" for item in previous_report["errors"])

    prev_state = previous.get("state")
    curr_state = current.get("state")
    allowed = {
        "UNCONSUMED": {"UNCONSUMED", "EVALUATING"},
        "EVALUATING": {"CLOSED"},
        "CLOSED": {"RELEASED_TO_FUTURE_TRAIN"},
        "RELEASED_TO_FUTURE_TRAIN": set(),
    }
    if prev_state in allowed and curr_state not in allowed[prev_state]:
        errors.append(f"invalid state transition {prev_state!r} -> {curr_state!r}")

    for field in ("holdout_id", "generation", "parent_holdout_id", "population_id", "precommit", "temporal_boundary"):
        if previous.get(field) != current.get(field):
            errors.append(f"{field} is immutable after freeze")

    expected_previous = canonical_sha256(previous)
    if current.get("previous_manifest_sha256") != expected_previous:
        errors.append("previous_manifest_sha256 does not match the canonical previous manifest")

    prev_hands = previous.get("hands") if isinstance(previous.get("hands"), list) else []
    curr_hands = current.get("hands") if isinstance(current.get("hands"), list) else []

    if prev_state == "UNCONSUMED" and curr_state == "UNCONSUMED":
        if len(curr_hands) < len(prev_hands):
            errors.append("append-only violation: hands were removed")
        else:
            for index, old_hand in enumerate(prev_hands):
                if old_hand != curr_hands[index]:
                    errors.append(f"append-only violation: hands[{index}] was modified")
    elif prev_state in {"UNCONSUMED", "EVALUATING"} and curr_state in {"EVALUATING", "CLOSED"}:
        if curr_hands != prev_hands:
            errors.append("ledger must be frozen once evaluation starts")
    elif prev_state == "CLOSED" and curr_state == "RELEASED_TO_FUTURE_TRAIN":
        if len(curr_hands) != len(prev_hands):
            errors.append("release cannot add or remove hands")
        else:
            for index, old_hand in enumerate(prev_hands):
                expected = copy.deepcopy(old_hand)
                if isinstance(expected, dict):
                    expected["train_eligible"] = True
                if curr_hands[index] != expected:
                    errors.append(f"release may only change hands[{index}].train_eligible false->true")

    report = dict(current_report)
    report["errors"] = errors
    report["warnings"] = warnings
    report["status"] = "FAIL" if errors else ("WARN" if warnings else "PASS")
    report["previous_manifest_sha256"] = expected_previous
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate a prospective temporal holdout ledger without running scientific evaluation."
    )
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--protocol", type=Path, default=Path("training/prospective/PROTOCOL.json"))
    parser.add_argument("--previous", type=Path, default=None)
    args = parser.parse_args(argv)

    try:
        protocol = load_json(args.protocol)
        manifest = load_json(args.manifest)
        report = (
            validate_transition(load_json(args.previous), manifest, protocol)
            if args.previous
            else validate_manifest(manifest, protocol)
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        report = {
            "schema": REPORT_SCHEMA,
            "status": "FAIL",
            "errors": [str(exc)],
            "warnings": [],
        }

    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 1 if report.get("status") == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())

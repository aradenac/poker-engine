#!/usr/bin/env python3
"""#421 T8: one-shot VALIDATION evaluation and terminal admission decision.

The T7 freeze
(``analysis/issue421_generalized_response/FROZEN_VALIDATION_PROTOCOL.json``,
canonical payload digest pinned in its ``.sha256`` sidecar) fixes the
thresholds, the pooling limits and the comparator set *before* the VALIDATION
holdout is opened.  This command is the single, one-shot evaluation that opens
it:

1. it re-derives the pinned protocol bytes and re-runs the ordering guard
   **before** a single VALIDATION hand is parsed
   (:func:`verify_protocol_frozen_before_validation`);
2. it reads the certified VALIDATION fold exactly once, fails closed on TEST,
   and proves the read is the registered fold (row/​hand counts and the
   ``hand_ids_fingerprint_sha256`` of the frozen dataset manifest);
3. it evaluates the frozen candidate against three explicit references --
   active Model A v5 (``training/models/preflop_population_model_v5.json``),
   the #352 sizing-aware v2 candidate, and the candidate's own frozen fit prior
   / alternate architecture -- on probabilistic quality (log loss, Brier),
   calibration (global and by family, equal-count reliability bins), coverage
   (total, ``LIMPER_VS_ISO``, per actor position, OOD abstention rate) and
   generalisation strata (frequent exacts, rare exacts, exact-but-absent
   in-domain, extrapolation / OOD);
4. it persists ``VALIDATION_RESULT.json`` and the terminal ``DECISION.json``.

Terminal outcome
----------------
``ADMIT_GENERALIZED_RESPONSE_MODEL`` only when all ten frozen admission
criteria hold; otherwise ``RETAIN_REFERENCE_GENERALIZATION_INSUFFICIENT``.
The evaluation admits nothing by itself: the active Model A pointer is never
mutated (``active_pointer_mutated=false``), the TEST split is never read
(``test_consumed=false``) and only an admitted outcome may be consumed
downstream.

Scientific boundaries
---------------------
* VALIDATION is read once, after the protocol bytes and the order guard are
  re-verified; TEST is refused statically (AST self-scan) and dynamically (the
  certified split loader and the model both fail closed on TEST).
* No threshold, prior, comparator or hyper-parameter is changed here: the
  numbers are re-asserted as frozen constants against the protocol payload.
* The active Model A v5 reference is re-hashed before and after the read and is
  never written to.
"""
from __future__ import annotations

import argparse
import ast
import collections
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.datasets.build_hand_history_increment import fingerprint  # noqa: E402
from tools.preflop import generalized_response_model as M  # noqa: E402
from tools.training import evaluate_generalized_response_cv as CV  # noqa: E402
from tools.training import fit_model_a_preflop_sizing as v1  # noqa: E402
from tools.training import fit_model_a_preflop_sizing_v2 as v2  # noqa: E402
from tools.training.build_generalized_response_dataset import (  # noqa: E402
    project_response_row,
)
from tools.training.evaluate_preflop_topology_candidate import (  # noqa: E402
    by_actor,
    find_closest,
)
from tools.training.fit_model_a_preflop_sizing import (  # noqa: E402
    load_certified_split,
)
from tools.training.increment_decisions import decision_rows, parse_hand  # noqa: E402
from tools.training.preflop_policy169 import (  # noqa: E402
    decode_policy169,
    hand_weights,
)

# ---------------------------------------------------------------------------
# paths and frozen identities
# ---------------------------------------------------------------------------

HERE = ROOT / "analysis/issue421_generalized_response"
PROTOCOL_PATH = HERE / "FROZEN_VALIDATION_PROTOCOL.json"
PROTOCOL_DIGEST_PATH = HERE / "FROZEN_VALIDATION_PROTOCOL.sha256"
DATASET_MANIFEST_PATH = HERE / "dataset/GENERALIZED_RESPONSE_DATASET.json"
DATASET_PATH = HERE / "dataset/GENERALIZED_RESPONSE_DATASET.jsonl"

RESULT_PATH = HERE / "VALIDATION_RESULT.json"
RESULT_DIGEST_PATH = HERE / "VALIDATION_RESULT.sha256"
DECISION_PATH = HERE / "DECISION.json"
DECISION_DIGEST_PATH = HERE / "DECISION.sha256"

CANDIDATE_PATH = HERE / "model/candidate_regularized_multinomial_spline.json"
ALTERNATE_CANDIDATE_PATH = (
    HERE / "model/candidate_hierarchical_empirical_bayes_dirichlet.json"
)
FIT_REPORT_PATH = HERE / "model/FIT_REPORT.json"
CV_REPORT_PATH = HERE / "TRAIN_CV_REPORT.json"
OOD_REPORT_PATH = HERE / "OOD_CALIBRATION_REPORT.json"
SIZING_REPORT_PATH = HERE / "RAISE_SIZING_MODEL_REPORT.json"

ACTIVE_MODEL_A_PATH = ROOT / "training/models/preflop_population_model_v5.json"
ISSUE352_FIT_PATH = ROOT / "analysis/model_a_preflop_sizing_v2_fit.json"
ISSUE352_VALIDATION_PATH = ROOT / "analysis/model_a_preflop_sizing_v2_validation.json"

#: The protocol this command executes.  Editing the protocol (for instance to
#: relax a threshold after the read) changes its bytes and is refused here,
#: before any VALIDATION decision is parsed.
EXPECTED_PROTOCOL_BYTE_SHA256 = (
    "ff91421b372dab869b8603fac04e7cb15b4b810f4c742c0fff4139786d97cdd5"
)
EXPECTED_PROTOCOL_CANONICAL_PAYLOAD_SHA256 = (
    "7c703fd934629b239293932fd0a7349957b0fdd48538154429f4597da74883ce"
)
EXPECTED_DATASET_SHA256 = (
    "4c18872fac5fc443e68e6f99feb0036509999f67f952c02e118671c7c72330a2"
)
EXPECTED_DATASET_ROWS = 105698
EXPECTED_VALIDATION_ROWS = 11538
EXPECTED_VALIDATION_HANDS = 2324
EXPECTED_VALIDATION_HANDS_FINGERPRINT = (
    "e0980444de231d5e38d07980ffdc238a48b6261691575715a5f458a8ebcd03ba"
)
EXPECTED_CANDIDATE_BYTE_SHA256 = (
    "ea93e8c35e2604debd943495474cdb9262d724efb4a5caefe3723b53f23a59e7"
)
EXPECTED_CANDIDATE_CANONICAL_SHA256 = (
    "c3f3573f3e80b3f7889dc8b1fd6f1948daeea95effc5a41a5d707385c4eed7dc"
)
EXPECTED_ALTERNATE_CANONICAL_SHA256 = (
    "7eb7b4794d9e42bcf151f7e1cf21c337a7f2393bfaf4a1ecc6b310793d2c302f"
)
EXPECTED_ACTIVE_MODEL_A_SHA256 = (
    "ff952055ca4ee051a3ac9607d513fdecac0a320a31f658ecfd8a11d8448975ca"
)
EXPECTED_ISSUE352_CANDIDATE_SHA256 = (
    "9115165c3141d16152946dd1ee7a049f219fef1a1d79c0e1c7b1249c45326f19"
)
EXPECTED_ISSUE352_FIT_BYTE_SHA256 = (
    "cd2a29a6574ff03ca09a39e3995d6df9fbd9e677e7e63a27e7d2438df1fb260e"
)
EXPECTED_ISSUE352_VALIDATION_BYTE_SHA256 = (
    "0e93640bd56e37d445438c9b663d2cb77b623f33d01dc91836ed12fd4651bf06"
)
EXPECTED_ISSUE352_VALIDATION_EVIDENCE_SHA256 = (
    "54f6e2affb0a088aa5148c981331abafe705ce7793433f89accbf304dc6f7496"
)

PROTOCOL_SCHEMA = "poker-generalized-frozen-validation-protocol/v1"
RESULT_SCHEMA = "poker-generalized-response-validation-result/v1"
DECISION_SCHEMA = "poker-generalized-response-terminal-decision/v1"
FROZEN_STATUS = "FROZEN_BEFORE_VALIDATION"

PROTOCOL_OUTCOME_ADMIT = "ADMIT_CANDIDATE"
PROTOCOL_OUTCOME_RETAIN = "RETAIN_ACTIVE_REFERENCE"
DECISION_ADMIT = "ADMIT_GENERALIZED_RESPONSE_MODEL"
DECISION_RETAIN = "RETAIN_REFERENCE_GENERALIZATION_INSUFFICIENT"

#: The two declared locations of the protocol's VALIDATION_ORDER_GUARD.  They
#: must stay empty for the freeze to remain verifiable; the T8 artifacts are
#: published at the directory-level paths named by the task scope.  Recorded so
#: the guard is re-run and its emptiness is explicit evidence.
GUARD_DECLARED_RESULT_LOCATIONS = (
    "analysis/issue421_generalized_response/validation/VALIDATION_RESULT.json",
    "analysis/issue421_generalized_response/validation/FROZEN_VALIDATION_RESULT.json",
)

ACTIONS = tuple(M.ACTIONS)
EPS = M.EPS
PROBABILITY_FLOOR = M.PROBABILITY_FLOOR
CALIBRATION_BINS = 10
CALIBRATION_MINIMUM_BIN_SUPPORT = 20
BOOTSTRAP_SAMPLES = 5000
BOOTSTRAP_CONFIDENCE = 0.95
BOOTSTRAP_SEED = 421

#: Non-inferiority margins from the frozen protocol (bits/decision).
MARGIN_FIT_GLOBAL_PRIOR = 0.0
MARGIN_ALTERNATE_ARCHITECTURE = 0.005
MARGIN_ACTIVE_MODEL_A = 0.0

#: Coverage floor from the frozen protocol.
MINIMUM_COVERAGE = 0.50
MINIMUM_SCORED_DECISIONS = 500
MINIMUM_DISTINCT_HANDS = 100

#: Calibration ceiling from the frozen protocol.
MAXIMUM_ABSOLUTE_ECE = 0.05
MAXIMUM_ECE_DELTA_VS_ACTIVE = 0.02

#: Symbols that would indicate a TEST/holdout loader.  The evaluation *must*
#: read VALIDATION, so only the TEST-side loaders are forbidden.
FORBIDDEN_TEST_LOADER_SYMBOLS = (
    "load_test_records",
    "TEST_HANDS",
    "test_hand_ids",
    "test_decisions",
    "load_holdout",
    "holdout_records",
)

MODEL_LABELS = (
    "candidate_generalized",
    "active_model_a_v5",
    "model_a_preflop_sizing_aware_candidate_v2",
    "fit_global_prior_baseline",
    "alternate_architecture_hierarchical_eb",
)


class ValidationExecutionError(RuntimeError):
    """Raised when the frozen protocol boundary would be crossed."""


# ---------------------------------------------------------------------------
# hashing helpers
# ---------------------------------------------------------------------------


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical_hash(value: Any) -> str:
    return M.stable_hash(value)


def serialize(payload: Any) -> bytes:
    return (json.dumps(payload, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def _round(value: Any, digits: int = 10) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return round(float(value), digits)
    return value


def _relative(path: Path) -> str:
    resolved = Path(path).resolve()
    try:
        return str(resolved.relative_to(ROOT))
    except ValueError:
        return str(resolved)


# ---------------------------------------------------------------------------
# guards
# ---------------------------------------------------------------------------


def verify_no_test_loader(source: str | None = None) -> dict[str, Any]:
    """AST self-scan: this command declares no TEST/holdout loader symbol."""
    text = Path(__file__).read_text() if source is None else source
    module = ast.parse(text)
    used: set[str] = set()
    for node in ast.walk(module):
        if isinstance(node, ast.Name):
            used.add(node.id)
        elif isinstance(node, ast.Attribute):
            used.add(node.attr)
    hits = sorted(used & set(FORBIDDEN_TEST_LOADER_SYMBOLS))
    if hits:
        raise ValidationExecutionError(f"TEST/holdout loader symbol used: {hits}")
    return {
        "check": "self_source_scan_for_test_loaders",
        "result": "PASS",
        "forbidden_symbols": list(FORBIDDEN_TEST_LOADER_SYMBOLS),
        "hits": [],
        "detail": (
            "AST scan: this evaluation command declares none of the forbidden TEST/holdout "
            "loader symbols; VALIDATION is read through the certified split loader, which "
            "fails closed on any non-VALIDATION record, and the model itself refuses TEST rows"
        ),
    }


def _declared_result_locations_present() -> list[str]:
    return [
        relative
        for relative in GUARD_DECLARED_RESULT_LOCATIONS
        if (ROOT / relative).is_file()
    ]


def verify_protocol_frozen_before_validation() -> dict[str, Any]:
    """Fail closed unless the protocol is frozen, unmoved and not yet consumed.

    The ordering guard is re-run *before* a single VALIDATION hand is parsed:
    the protocol bytes are re-derived against the pinned digest, the freeze
    status is asserted and the declared fenced-result locations are proven
    empty, so thresholds, comparators and pooling limits cannot have been
    edited after the holdout was seen.
    """
    if not PROTOCOL_PATH.is_file():
        raise ValidationExecutionError(
            "no frozen VALIDATION protocol; VALIDATION is forbidden"
        )
    payload = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))
    if payload.get("schema") != PROTOCOL_SCHEMA:
        raise ValidationExecutionError(
            f"unexpected frozen protocol schema: {payload.get('schema')!r}"
        )
    if payload.get("status") != FROZEN_STATUS:
        raise ValidationExecutionError(
            f"protocol must be {FROZEN_STATUS} before evaluation, "
            f"got {payload.get('status')!r}"
        )
    actual_bytes = sha256_file(PROTOCOL_PATH)
    if actual_bytes != EXPECTED_PROTOCOL_BYTE_SHA256:
        raise ValidationExecutionError(
            "frozen VALIDATION protocol was mutated after the freeze: "
            f"{actual_bytes} != {EXPECTED_PROTOCOL_BYTE_SHA256}"
        )
    if not PROTOCOL_DIGEST_PATH.is_file():
        raise ValidationExecutionError("the frozen protocol .sha256 sidecar is missing")
    sidecar = PROTOCOL_DIGEST_PATH.read_text(encoding="utf-8")
    if not sidecar.startswith(EXPECTED_PROTOCOL_BYTE_SHA256 + "  "):
        raise ValidationExecutionError("the protocol .sha256 sidecar does not pin the protocol")
    actual_canonical = canonical_hash(payload)
    if actual_canonical != EXPECTED_PROTOCOL_CANONICAL_PAYLOAD_SHA256:
        raise ValidationExecutionError(
            "the frozen protocol canonical payload drifted: "
            f"{actual_canonical} != {EXPECTED_PROTOCOL_CANONICAL_PAYLOAD_SHA256}"
        )
    present = _declared_result_locations_present()
    if present:
        raise ValidationExecutionError(
            "a fenced VALIDATION result already exists; the holdout was already read: "
            + ", ".join(present)
        )
    return {
        "guard_id": "VALIDATION_ORDER_GUARD",
        "result": "PASS",
        "protocol_path": _relative(PROTOCOL_PATH),
        "protocol_byte_sha256": actual_bytes,
        "protocol_canonical_payload_sha256": actual_canonical,
        "status": payload["status"],
        "frozen_at": payload.get("frozen_at"),
        "frozen_at_epoch": payload.get("frozen_at_epoch"),
        "declared_result_locations": list(GUARD_DECLARED_RESULT_LOCATIONS),
        "declared_result_locations_present": present,
        "validation_read_before_protocol_hash": False,
        "detail": (
            "the pinned protocol bytes and canonical payload digest were re-derived before a "
            "single VALIDATION hand was parsed; the declared fenced-result locations are empty"
        ),
    }


def assert_result_not_yet_persisted() -> None:
    """One-shot rule: refuse to open VALIDATION when a terminal result exists."""
    if RESULT_PATH.is_file() or DECISION_PATH.is_file():
        raise ValidationExecutionError(
            "a terminal #421 VALIDATION result already exists; the holdout is consumed and "
            f"cannot be read again ({_relative(RESULT_PATH)}, {_relative(DECISION_PATH)})"
        )


# ---------------------------------------------------------------------------
# comparators
# ---------------------------------------------------------------------------


def _map_reference_action(name: Any) -> str | None:
    """Map a comparator action label onto the public response action space."""
    text = str(name or "").strip().upper()
    if text == "LIMP":
        text = "CALL"
    return text if text in M.ACTION_INDEX else None


def _normalized(distribution: Mapping[str, float]) -> tuple[dict[str, float] | None, float]:
    """Normalize a mapped action mass onto the four response actions."""
    mapped = {action: 0.0 for action in ACTIONS}
    for action, value in distribution.items():
        target = _map_reference_action(action)
        if target is None:
            continue
        mapped[target] += max(0.0, float(value or 0.0))
    total = sum(mapped.values())
    if total <= EPS:
        return None, 0.0
    dropped = max(0.0, 1.0 - total)
    return {action: mapped[action] / total for action in ACTIONS}, dropped


def load_candidate() -> dict[str, Any]:
    if sha256_file(CANDIDATE_PATH) != EXPECTED_CANDIDATE_BYTE_SHA256:
        raise ValidationExecutionError("generalized candidate byte hash drifted")
    candidate = M.load_candidate(CANDIDATE_PATH)
    if candidate["canonical_payload_sha256"] != EXPECTED_CANDIDATE_CANONICAL_SHA256:
        raise ValidationExecutionError("generalized candidate canonical digest drifted")
    return candidate


def load_alternate_candidate() -> dict[str, Any]:
    alternate = M.load_candidate(ALTERNATE_CANDIDATE_PATH)
    if alternate["canonical_payload_sha256"] != EXPECTED_ALTERNATE_CANONICAL_SHA256:
        raise ValidationExecutionError("alternate architecture canonical digest drifted")
    return alternate


def build_comparators() -> dict[str, Any]:
    """Re-pin every reference by content digest and load it."""
    if sha256_file(ACTIVE_MODEL_A_PATH) != EXPECTED_ACTIVE_MODEL_A_SHA256:
        raise ValidationExecutionError("active Model A v5 reference hash drifted")
    if sha256_file(ISSUE352_FIT_PATH) != EXPECTED_ISSUE352_FIT_BYTE_SHA256:
        raise ValidationExecutionError("#352 fit artifact byte hash drifted")
    if sha256_file(ISSUE352_VALIDATION_PATH) != EXPECTED_ISSUE352_VALIDATION_BYTE_SHA256:
        raise ValidationExecutionError("#352 validation evidence byte hash drifted")
    evidence = json.loads(ISSUE352_VALIDATION_PATH.read_text(encoding="utf-8"))
    if evidence.get("evidence_sha256") != EXPECTED_ISSUE352_VALIDATION_EVIDENCE_SHA256:
        raise ValidationExecutionError("#352 validation evidence digest drifted")
    if evidence.get("test_consumed") is not False:
        raise ValidationExecutionError("#352 evidence must declare test_consumed=false")

    fit_protocol = v2.load_fit_protocol()
    _, report = v1.load_support_report()
    candidate_v2, fit_v2 = v2.build_candidate(fit_protocol, report)
    if fit_v2["candidate_sha256"] != EXPECTED_ISSUE352_CANDIDATE_SHA256:
        raise ValidationExecutionError("#352 candidate reconstruction drifted")
    persisted = json.loads(ISSUE352_FIT_PATH.read_text(encoding="utf-8"))
    if persisted.get("candidate_sha256") != EXPECTED_ISSUE352_CANDIDATE_SHA256:
        raise ValidationExecutionError("#352 persisted candidate identity drifted")

    active_model = json.loads(ACTIVE_MODEL_A_PATH.read_text(encoding="utf-8"))
    return {
        "active_model": active_model,
        "active_index": by_actor(active_model.get("nodes") or []),
        "active_grid": list((active_model.get("hand_grid") or {}).get("classes") or []),
        "active_weights": hand_weights(
            list((active_model.get("hand_grid") or {}).get("classes") or []),
            (active_model.get("hand_grid") or {}).get("meta"),
        ),
        "v2_index": v1._candidate_index(candidate_v2),
        "v2_fit": fit_v2,
    }


def active_public_distribution(
    comparators: Mapping[str, Any], row: Mapping[str, Any]
) -> dict[str, Any]:
    """Marginal public action distribution of active Model A v5 at one decision.

    The v5 node policy is hand-conditioned over the 169 hand classes; the public
    comparator is the combo-weighted marginal over hands, mapped onto the
    response space (``LIMP`` -> ``CALL``) and renormalized on the four response
    actions so a paired comparison scores the same requested decision.
    """
    match = find_closest(dict(comparators["active_index"]), dict(row))
    if not match:
        return {"available": False, "probabilities": None, "reason": "NO_ACTIVE_NODE"}
    node = match["node"]
    raw: dict[str, float] = {}
    try:
        policy = decode_policy169(node, comparators["active_grid"])
        for hand, weights in comparators["active_weights"].items():
            entry = policy.get(hand) or {}
            for action, value in entry.items():
                raw[action] = raw.get(action, 0.0) + float(weights) * float(value)
        source = "POLICY169_COMBO_WEIGHTED"
    except (ValueError, TypeError, KeyError):
        frequencies = (node.get("population_model") or {}).get("frequencies") or {}
        raw = {str(action): float(value or 0.0) for action, value in frequencies.items()}
        source = "MARGINAL_FREQUENCY"
    probabilities, dropped = _normalized(raw)
    if probabilities is None:
        return {"available": False, "probabilities": None, "reason": "ACTIVE_NODE_EMPTY"}
    return {
        "available": True,
        "probabilities": probabilities,
        "exact": bool(match.get("exact")),
        "source": source,
        "dropped_non_response_mass": dropped,
    }


def v2_public_distribution(
    comparators: Mapping[str, Any], row: Mapping[str, Any]
) -> dict[str, Any]:
    """Public action distribution of the #352 sizing-aware v2 candidate."""
    try:
        key = v1.support_context_key(row)
    except Exception:  # noqa: BLE001 - any missing public price is a fail-closed miss
        return {"available": False, "probabilities": None, "reason": "NO_SUPPORT_KEY"}
    node = comparators["v2_index"].get((key, None))
    if node is None:
        return {"available": False, "probabilities": None, "reason": "NO_V2_SUPPORT_NODE"}
    probabilities, dropped = _normalized(node.get("probabilities") or {})
    if probabilities is None:
        return {"available": False, "probabilities": None, "reason": "V2_NODE_EMPTY"}
    return {
        "available": True,
        "probabilities": probabilities,
        "support_context_key": key,
        "support": node.get("support"),
        "support_class": node.get("support_class"),
        "dropped_non_response_mass": dropped,
    }


# ---------------------------------------------------------------------------
# the VALIDATION read (exactly once)
# ---------------------------------------------------------------------------


def read_validation_rows() -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Read the certified VALIDATION fold exactly once.

    Returns the public response rows (the candidate surface), the paired
    full-context decision rows (the comparator surface, ``preflop_context_v1``
    included) and the read evidence.  TEST is refused by the loader and asserted
    row by row.
    """
    records, provenance = load_certified_split("VALIDATION")
    hand_ids = [str(record.hand_id) for record in records]
    observed_fingerprint = fingerprint(hand_ids)
    if provenance.get("split") != "VALIDATION":
        raise ValidationExecutionError("the certified loader returned a non-VALIDATION split")
    if observed_fingerprint != EXPECTED_VALIDATION_HANDS_FINGERPRINT:
        raise ValidationExecutionError(
            "the certified loader returned a different VALIDATION fold: "
            f"{observed_fingerprint} != {EXPECTED_VALIDATION_HANDS_FINGERPRINT}"
        )

    public_rows: list[dict[str, Any]] = []
    decision_rows_full: list[dict[str, Any]] = []
    test_rows_seen = 0
    for record in records:
        hand = parse_hand(record.text, record.source_file)
        if not hand:
            raise ValidationExecutionError(
                f"VALIDATION hand failed normalization: {record.hand_id}"
            )
        for row in decision_rows(hand, include_preflop_context_v1=True):
            split = str(row.get("split") or "").upper()
            if split != "VALIDATION":
                test_rows_seen += 1
                raise ValidationExecutionError("a non-VALIDATION decision row crossed the evaluator")
            projected = project_response_row(row, split="VALIDATION")
            if projected is None:
                continue
            public_rows.append(projected)
            decision_rows_full.append(dict(row))

    if len(public_rows) != len(decision_rows_full):
        raise ValidationExecutionError("the public and full-context row sets diverged")
    if len(public_rows) != EXPECTED_VALIDATION_ROWS:
        raise ValidationExecutionError(
            f"VALIDATION row count drifted: {len(public_rows)} != {EXPECTED_VALIDATION_ROWS}"
        )
    evidence = {
        "split": "VALIDATION",
        "reads": 1,
        "hands_parsed": len(records),
        "rows": len(public_rows),
        "distinct_hands": len({str(row["hand_id"]) for row in public_rows}),
        "hand_ids_fingerprint_sha256": observed_fingerprint,
        "expected_rows": EXPECTED_VALIDATION_ROWS,
        "expected_hands": EXPECTED_VALIDATION_HANDS,
        "expected_hand_ids_fingerprint_sha256": EXPECTED_VALIDATION_HANDS_FINGERPRINT,
        "test_rows_seen": test_rows_seen,
        "test_consumed": False,
        "loader_provenance": {
            key: value for key, value in sorted(provenance.items()) if key != "archives"
        },
        "loader": "tools/training/fit_model_a_preflop_sizing.load_certified_split",
    }
    return public_rows, decision_rows_full, evidence


# ---------------------------------------------------------------------------
# metrics
# ---------------------------------------------------------------------------


def _nll(probabilities: Mapping[str, float], observed: str) -> float:
    return -math.log2(max(float(probabilities.get(observed, 0.0)), PROBABILITY_FLOOR))


def _record(
    public: Mapping[str, Any],
    observed: str,
    probabilities: Mapping[str, float],
    *,
    stratum: str,
    ood_status: str,
    answered: bool,
    family: str,
    actor_position: str,
) -> dict[str, Any]:
    legal = set(M.legal_response_actions(public))
    return {
        "hand_id": str(public.get("hand_id") or "").strip(),
        "observed": observed,
        "probabilities": {action: float(probabilities[action]) for action in ACTIONS},
        "masked_actions": [action for action in ACTIONS if action not in legal],
        "stratum": stratum,
        "ood_status": ood_status,
        "answered": bool(answered),
        "family": family,
        "actor_position": actor_position,
    }


def _subset_metrics(
    records: Sequence[Mapping[str, Any]], prior: Mapping[str, float]
) -> dict[str, Any]:
    summary = CV.summary_metrics(records, prior)
    return {
        "n": summary["n"],
        "log_loss_bits_per_decision": _round(summary["log_loss_bits_per_decision"]),
        "baseline_log_loss_bits_per_decision": _round(
            summary["baseline_log_loss_bits_per_decision"]
        ),
        "gain_bits_per_decision": _round(summary["gain_bits_per_decision"]),
        "brier_score": _round(summary["brier_score"]),
        "accuracy": _round(summary["accuracy"]),
        "expected_calibration_error": _round(
            summary["expected_calibration_error"]["ece"]
        ),
        "bins_meeting_minimum_support": summary["expected_calibration_error"][
            "bins_meeting_minimum_support"
        ],
        "claim_supportable": bool(
            summary["expected_calibration_error"]["claim_supportable"]
        ),
    }


def _calibration_detail(
    records: Sequence[Mapping[str, Any]],
    *,
    bins: int = CALIBRATION_BINS,
    minimum_bin_support: int = CALIBRATION_MINIMUM_BIN_SUPPORT,
) -> dict[str, Any]:
    detail = CV.expected_calibration_error(
        records, bins=bins, minimum_bin_support=minimum_bin_support
    )
    return {
        "pooled_support_rows": len(records),
        "ece": _round(detail["ece"], 12),
        "per_action_class": {
            action: _round(value, 12) for action, value in detail["per_action_class"].items()
        },
        "bins_per_action_class": detail["bins_per_action_class"],
        "minimum_bin_support": detail["minimum_bin_support"],
        "bins_meeting_minimum_support": detail["bins_meeting_minimum_support"],
        "claim_supportable": bool(detail["claim_supportable"]),
    }


def _coverage_block(
    records: Sequence[Mapping[str, Any]],
    *,
    total_rows: int,
) -> dict[str, Any]:
    answered = [record for record in records if record["answered"]]
    statuses = collections.Counter(record["ood_status"] for record in records)
    by_family: dict[str, Any] = {}
    by_position: dict[str, Any] = {}
    for attribution, key in (("family", by_family), ("actor_position", by_position)):
        grouped: dict[str, list[Mapping[str, Any]]] = collections.defaultdict(list)
        for record in records:
            grouped[str(record[attribution])].append(record)
        for value, members in sorted(grouped.items()):
            covered = sum(1 for member in members if member["answered"])
            key[value] = {
                "n": len(members),
                "answered": covered,
                "coverage": _round(covered / len(members)) if members else None,
                "abstain_rate": _round(1.0 - covered / len(members)) if members else None,
            }
    distinct_hands = len({record["hand_id"] for record in answered})
    return {
        "definition": (
            "share of in-scope VALIDATION decisions the frozen candidate answers with a legal, "
            "non-OOD distribution; abstaining is fail-closed and counted as non-covered"
        ),
        "universe_rows": total_rows,
        "answered_decisions": len(answered),
        "abstained_decisions": total_rows - len(answered),
        "coverage": _round(len(answered) / total_rows) if total_rows else None,
        "abstain_rate": _round((total_rows - len(answered)) / total_rows) if total_rows else None,
        "distinct_hands_answered": distinct_hands,
        "ood_status_counts": {status: statuses.get(status, 0) for status in M.OOD_STATUSES},
        "limiters_vs_iso": by_family.get("LIMPER_VS_ISO"),
        "by_family": by_family,
        "by_position": by_position,
    }


def _strata_block(
    records: Sequence[Mapping[str, Any]], prior: Mapping[str, float]
) -> dict[str, Any]:
    total = len(records)
    counts = {
        name: sum(1 for record in records if record["stratum"] == name)
        for name in M.OOD_STRATA
    }
    strata: dict[str, Any] = {}
    for name in M.OOD_STRATA:
        members = [record for record in records if record["stratum"] == name]
        answered = [record for record in members if record["answered"]]
        strata[name] = {
            "n": len(members),
            "share": _round(len(members) / total) if total else None,
            "coverage": _round(len(answered) / len(members)) if members else None,
            "abstain_rate": _round(1.0 - len(answered) / len(members)) if members else None,
            "metric_status": (
                "insufficient_support" if len(answered) < CALIBRATION_MINIMUM_BIN_SUPPORT else "scored"
            ),
            "answered_metrics": _subset_metrics(answered, prior),
        }
    return {
        "definition": (
            "generalisation strata of the frozen TRAIN-only OOD calibration: frequent exacts "
            "(exact cell support >= 20), rare exacts (0 < support < 20), exact cell absent but "
            "every single-feature label in-domain, and exact-absent out-of-domain / extrapolation"
        ),
        "frequent_exact_min_support": M.OOD_FREQUENT_EXACT_MIN_SUPPORT,
        "counts": counts,
        "share": {
            name: (_round(counts[name] / total) if total else None) for name in M.OOD_STRATA
        },
        "strata": strata,
    }


def _by_family_block(
    records: Sequence[Mapping[str, Any]], prior: Mapping[str, float]
) -> dict[str, Any]:
    grouped: dict[str, list[Mapping[str, Any]]] = collections.defaultdict(list)
    for record in records:
        grouped[str(record["family"])].append(record)
    total = len(records)
    out: dict[str, Any] = {}
    for family, members in sorted(grouped.items()):
        answered = [record for record in members if record["answered"]]
        out[family] = {
            "n": len(members),
            "share": _round(len(members) / total) if total else None,
            "coverage": _round(len(answered) / len(members)) if members else None,
            "answered_metrics": _subset_metrics(answered, prior),
        }
    return out


def _paired_delta(
    records: Sequence[Mapping[str, Any]],
    left_key: str,
    right_key: str,
    *,
    seed: int,
) -> dict[str, Any]:
    detail = [
        {
            "hand_id": str(record["hand_id"]),
            "delta_nll": (
                _nll(record[left_key], record["observed"])
                - _nll(record[right_key], record["observed"])
            ),
        }
        for record in records
    ]
    bootstrap = v1.bootstrap(detail, samples=BOOTSTRAP_SAMPLES, seed=seed)
    return {
        "left": left_key,
        "right": right_key,
        "n": len(detail),
        "hands": bootstrap["hands"],
        "delta_log_loss_bits_per_decision": _round(bootstrap["mean"]),
        "paired_bootstrap": {
            "method": "paired_percentile_bootstrap",
            "paired_unit": "hand_id",
            "samples": bootstrap["samples"],
            "seed": bootstrap["seed"],
            "confidence_level": BOOTSTRAP_CONFIDENCE,
            "ci95": [_round(bootstrap["ci95"][0]), _round(bootstrap["ci95"][1])],
            "probability_candidate_better": _round(bootstrap["probability_candidate_better"]),
        },
    }


# ---------------------------------------------------------------------------
# the evaluation
# ---------------------------------------------------------------------------


def evaluate() -> tuple[dict[str, Any], dict[str, Any]]:
    """Open VALIDATION once, score every reference and decide."""
    guard_evidence = verify_protocol_frozen_before_validation()
    assert_result_not_yet_persisted()
    test_scan = verify_no_test_loader()

    for label, path, expected in (
        ("dataset", DATASET_PATH, EXPECTED_DATASET_SHA256),
        ("dataset manifest", DATASET_MANIFEST_PATH, None),
        ("fit report", FIT_REPORT_PATH, None),
        ("train cv report", CV_REPORT_PATH, None),
        ("ood calibration report", OOD_REPORT_PATH, None),
        ("raise sizing report", SIZING_REPORT_PATH, None),
        ("active Model A v5", ACTIVE_MODEL_A_PATH, EXPECTED_ACTIVE_MODEL_A_SHA256),
    ):
        if not path.is_file():
            raise ValidationExecutionError(f"{label} is missing: {_relative(path)}")
        if expected is not None and sha256_file(path) != expected:
            raise ValidationExecutionError(f"{label} hash drifted")
    active_before = sha256_file(ACTIVE_MODEL_A_PATH)

    candidate = load_candidate()
    alternate = load_alternate_candidate()
    comparators = build_comparators()
    calibration = M.load_ood_calibration()

    prior = {action: float(candidate["params"]["prior"][action]) for action in ACTIONS}
    alternate_prior = {
        action: float(alternate["params"]["prior"][action]) for action in ACTIONS
    }
    if canonical_hash(alternate_prior) != canonical_hash(prior):
        raise ValidationExecutionError(
            "the two fitted architectures disagree on the global action prior"
        )

    public_rows, decision_rows, read_evidence = read_validation_rows()

    records: list[dict[str, Any]] = []
    active_dropped = 0.0
    active_exact = 0
    derived_illegal = 0
    for public, decision in zip(public_rows, decision_rows):
        observed = str(public["action"])
        if observed not in M.legal_response_actions(public):
            derived_illegal += 1
            continue
        family = M.categorical_node("family", public)
        actor_position = M.categorical_node("actor_position", public)
        response = M.predict(candidate, public)
        candidate_probabilities = response["probabilities"]
        gate = M.ood_gate_decision(candidate, public, calibration=calibration)
        answered = gate["status"] != M.STATUS_MODEL_OOD_ABSTAIN
        signature_support = int(gate["signals"]["exact_context"]["support"])
        in_domain = not gate["signals"]["unseen_categories"]
        stratum = M._ood_stratum(signature_support, in_domain)

        active = active_public_distribution(comparators, decision)
        v2 = v2_public_distribution(comparators, decision)
        alternate_probabilities = M.predict(alternate, public)["probabilities"]
        active_dropped += float(active.get("dropped_non_response_mass") or 0.0)
        active_exact += 1 if active.get("exact") else 0

        record = _record(
            public,
            observed,
            candidate_probabilities,
            stratum=stratum,
            ood_status=gate["status"],
            answered=answered,
            family=family,
            actor_position=actor_position,
        )
        record["candidate_generalized"] = record["probabilities"]
        record["active_model_a_v5"] = active["probabilities"]
        record["active_available"] = bool(active["available"])
        record["model_a_preflop_sizing_aware_candidate_v2"] = v2["probabilities"]
        record["v2_available"] = bool(v2["available"])
        record["fit_global_prior_baseline"] = dict(prior)
        record["alternate_architecture_hierarchical_eb"] = {
            action: float(alternate_probabilities[action]) for action in ACTIONS
        }
        record["ood_hard_reasons"] = list(gate["hard_reasons"])
        record["ood_soft_reasons"] = list(gate["soft_reasons"])
        record["active_exact"] = bool(active.get("exact"))
        records.append(record)

    active_after = sha256_file(ACTIVE_MODEL_A_PATH)
    if active_before != active_after:
        raise ValidationExecutionError("the active Model A v5 pointer mutated during the evaluation")

    total_rows = len(records)
    answered_records = [record for record in records if record["answered"]]

    # ---- paired comparison universes -------------------------------------
    paired_active = [
        record for record in answered_records if record["active_available"]
    ]
    paired_v2 = [record for record in answered_records if record["v2_available"]]
    paired_all = [
        record
        for record in answered_records
        if record["active_available"] and record["v2_available"]
    ]

    # ---- primary and secondary metric surface ---------------------------
    model_metrics: dict[str, Any] = {}
    for label in MODEL_LABELS:
        scored = answered_records
        if label == "active_model_a_v5":
            scored = paired_active
        if label == "model_a_preflop_sizing_aware_candidate_v2":
            scored = paired_v2
        metric_records = [
            dict(record, observed=record["observed"], probabilities=record[label])
            for record in scored
        ]
        model_metrics[label] = _subset_metrics(metric_records, prior)

    def _metric_records(
        label: str, scored: Sequence[Mapping[str, Any]]
    ) -> list[dict[str, Any]]:
        return [
            dict(record, observed=record["observed"], probabilities=record[label])
            for record in scored
        ]

    global_calibration = {
        label: _round(model_metrics[label]["expected_calibration_error"])
        for label in MODEL_LABELS
    }
    calibration_detail = {
        label: _calibration_detail(
            _metric_records(
                label,
                paired_active
                if label == "active_model_a_v5"
                else paired_v2
                if label == "model_a_preflop_sizing_aware_candidate_v2"
                else answered_records,
            )
        )
        for label in MODEL_LABELS
    }

    #: The frozen ceiling compares the candidate and the active reference on the
    #: *same* pooled support (the protocol's ``claim_requires``), so the gate uses
    #: a dedicated paired ECE rather than the two per-model universes.
    paired_candidate_ece = _calibration_detail(
        _metric_records("candidate_generalized", paired_active)
    )
    paired_active_ece = _calibration_detail(
        _metric_records("active_model_a_v5", paired_active)
    )

    coverage_block = _coverage_block(records, total_rows=total_rows)
    strata_block = _strata_block(records, prior)
    by_family_block = _by_family_block(records, prior)

    comparisons = {
        "candidate_minus_active_model_a_v5": _paired_delta(
            paired_active, "candidate_generalized", "active_model_a_v5", seed=BOOTSTRAP_SEED
        ),
        "candidate_minus_model_a_preflop_sizing_aware_candidate_v2": _paired_delta(
            paired_v2,
            "candidate_generalized",
            "model_a_preflop_sizing_aware_candidate_v2",
            seed=BOOTSTRAP_SEED + 1,
        ),
        "candidate_minus_fit_global_prior_baseline": _paired_delta(
            answered_records,
            "candidate_generalized",
            "fit_global_prior_baseline",
            seed=BOOTSTRAP_SEED + 2,
        ),
        "candidate_minus_alternate_architecture_hierarchical_eb": _paired_delta(
            answered_records,
            "candidate_generalized",
            "alternate_architecture_hierarchical_eb",
            seed=BOOTSTRAP_SEED + 3,
        ),
    }

    # ---- coverage / calibration gates -----------------------------------
    coverage_value = coverage_block["coverage"]
    distinct_hands_answered = coverage_block["distinct_hands_answered"]
    ece = paired_candidate_ece["ece"]
    active_ece = paired_active_ece["ece"]
    ece_claim_supportable = bool(paired_candidate_ece["claim_supportable"])
    ece_delta = (
        _round(ece - active_ece) if ece is not None and active_ece is not None else None
    )

    non_inferiority = {
        "fit_global_prior_baseline": {
            "margin_bits": MARGIN_FIT_GLOBAL_PRIOR,
            "ci95_upper": comparisons["candidate_minus_fit_global_prior_baseline"][
                "paired_bootstrap"
            ]["ci95"][1],
        },
        "alternate_architecture_hierarchical_eb": {
            "margin_bits": MARGIN_ALTERNATE_ARCHITECTURE,
            "ci95_upper": comparisons[
                "candidate_minus_alternate_architecture_hierarchical_eb"
            ]["paired_bootstrap"]["ci95"][1],
        },
        "active_model_a_v5": {
            "margin_bits": MARGIN_ACTIVE_MODEL_A,
            "ci95_upper": comparisons["candidate_minus_active_model_a_v5"][
                "paired_bootstrap"
            ]["ci95"][1],
        },
    }

    def _gate(
        gate_id: str,
        rule_id: str,
        passed: bool,
        observed: Any,
        threshold: Any,
        detail: str,
    ) -> dict[str, Any]:
        return {
            "id": gate_id,
            "rule_id": rule_id,
            "passed": bool(passed),
            "observed": observed,
            "threshold": threshold,
            "detail": detail,
        }

    gates = [
        _gate(
            "protocol_frozen_before_validation",
            "VALIDATION_ORDER_GUARD",
            True,
            {
                "protocol_byte_sha256": guard_evidence["protocol_byte_sha256"],
                "declared_result_locations_present": guard_evidence[
                    "declared_result_locations_present"
                ],
            },
            {"protocol_byte_sha256": EXPECTED_PROTOCOL_BYTE_SHA256},
            "the protocol bytes and canonical payload digest were re-derived and the ordering "
            "guard passed before the read",
        ),
        _gate(
            "test_never_consumed",
            "TEST_IS_NOT_AUTHORIZED",
            read_evidence["test_rows_seen"] == 0,
            {"test_rows_seen": read_evidence["test_rows_seen"], "test_consumed": False},
            {"test_rows_seen": 0},
            "TEST is refused statically by the AST self-scan and dynamically by the certified "
            "loader and the response model",
        ),
        _gate(
            "validation_read_exactly_once",
            "VALIDATION_READ_ONCE",
            read_evidence["reads"] == 1
            and read_evidence["rows"] == EXPECTED_VALIDATION_ROWS
            and read_evidence["hand_ids_fingerprint_sha256"]
            == EXPECTED_VALIDATION_HANDS_FINGERPRINT,
            {
                "reads": read_evidence["reads"],
                "rows": read_evidence["rows"],
                "hand_ids_fingerprint_sha256": read_evidence[
                    "hand_ids_fingerprint_sha256"
                ],
            },
            {
                "reads": 1,
                "rows": EXPECTED_VALIDATION_ROWS,
                "hand_ids_fingerprint_sha256": EXPECTED_VALIDATION_HANDS_FINGERPRINT,
            },
            "VALIDATION was opened once, after the freeze, and the read is the certified fold "
            "registered in the frozen dataset manifest",
        ),
        _gate(
            "coverage_floor",
            "COVERAGE_FLOOR",
            coverage_value is not None and coverage_value >= MINIMUM_COVERAGE,
            coverage_value,
            MINIMUM_COVERAGE,
            "share of in-scope VALIDATION decisions answered with a legal, non-OOD distribution",
        ),
        _gate(
            "minimum_scored_decisions",
            "COVERAGE_FLOOR",
            coverage_block["answered_decisions"] >= MINIMUM_SCORED_DECISIONS,
            coverage_block["answered_decisions"],
            MINIMUM_SCORED_DECISIONS,
            "minimum number of scored VALIDATION decisions",
        ),
        _gate(
            "minimum_distinct_hands",
            "COVERAGE_FLOOR",
            distinct_hands_answered >= MINIMUM_DISTINCT_HANDS,
            distinct_hands_answered,
            MINIMUM_DISTINCT_HANDS,
            "minimum number of distinct scored VALIDATION hands",
        ),
        _gate(
            "non_inferiority_vs_fit_global_prior_baseline",
            "CANDIDATE_NOT_INFERIOR_TO_COMPARATORS",
            non_inferiority["fit_global_prior_baseline"]["ci95_upper"]
            <= MARGIN_FIT_GLOBAL_PRIOR,
            non_inferiority["fit_global_prior_baseline"],
            {"ci95_upper_max": MARGIN_FIT_GLOBAL_PRIOR},
            "paired (candidate - fit global action prior) 95% CI upper bound <= 0",
        ),
        _gate(
            "non_inferiority_vs_alternate_architecture_hierarchical_eb",
            "CANDIDATE_NOT_INFERIOR_TO_COMPARATORS",
            non_inferiority["alternate_architecture_hierarchical_eb"]["ci95_upper"]
            <= MARGIN_ALTERNATE_ARCHITECTURE,
            non_inferiority["alternate_architecture_hierarchical_eb"],
            {"ci95_upper_max": MARGIN_ALTERNATE_ARCHITECTURE},
            "paired (candidate - hierarchical empirical Bayes) 95% CI upper bound <= the "
            "preregistered cross-validation tolerance",
        ),
        _gate(
            "non_inferiority_vs_active_model_a_preflop_population",
            "CANDIDATE_NOT_INFERIOR_TO_COMPARATORS",
            non_inferiority["active_model_a_v5"]["ci95_upper"] <= MARGIN_ACTIVE_MODEL_A,
            non_inferiority["active_model_a_v5"],
            {"ci95_upper_max": MARGIN_ACTIVE_MODEL_A},
            "paired (candidate - active Model A v5) 95% CI upper bound <= 0",
        ),
        _gate(
            "calibration_within_frozen_ceiling",
            "CALIBRATION_WITHIN_FROZEN_CEILING",
            ece is not None
            and ece_claim_supportable
            and ece <= MAXIMUM_ABSOLUTE_ECE
            and ece_delta is not None
            and ece_delta <= MAXIMUM_ECE_DELTA_VS_ACTIVE,
            {
                "ece": ece,
                "active_ece": active_ece,
                "ece_delta_vs_active": ece_delta,
                "claim_supportable": ece_claim_supportable,
                "bins_meeting_minimum_support": paired_candidate_ece[
                    "bins_meeting_minimum_support"
                ],
                "pooled_support_rows": paired_candidate_ece["pooled_support_rows"],
                "active_ece_on_same_support": active_ece,
            },
            {
                "maximum_absolute_ece": MAXIMUM_ABSOLUTE_ECE,
                "maximum_ece_delta_vs_active": MAXIMUM_ECE_DELTA_VS_ACTIVE,
                "minimum_bin_support_for_a_claim": CALIBRATION_MINIMUM_BIN_SUPPORT,
            },
            "equal-count reliability bins per action class, pooled over the frozen VALIDATION "
            "decisions and compared against the active reference",
        ),
    ]

    passed = [gate["id"] for gate in gates if gate["passed"]]
    failed = [gate["id"] for gate in gates if not gate["passed"]]
    all_gates_pass = not failed
    outcome = PROTOCOL_OUTCOME_ADMIT if all_gates_pass else PROTOCOL_OUTCOME_RETAIN
    decision = DECISION_ADMIT if all_gates_pass else DECISION_RETAIN

    sizing_diagnostic = M._score_sizing_rows(
        M.sizing_channel_of(candidate),
        [row for row in public_rows if str(row.get("action")) in M.AGGRESSIVE_ACTIONS],
        M.make_config(),
        steps=M.SIZING_QUADRATURE_STEPS,
        min_family_support=M.MIN_FAMILY_SIZING_SUPPORT,
    )

    result: dict[str, Any] = {
        "schema": RESULT_SCHEMA,
        "issue": 421,
        "protocol": guard_evidence,
        "split": "VALIDATION",
        "split_opened": True,
        "validation_reads": read_evidence["reads"],
        "test_consumed": False,
        "test_authorized": False,
        "evaluation_universe": {
            "definition": (
                "non-Hero public preflop response decisions of the certified VALIDATION fold "
                "where the candidate and every comparator answer the same requested public context"
            ),
            "in_scope_rows": total_rows,
            "in_scope_hands": len({record["hand_id"] for record in records}),
            "rows_dropped_observed_action_illegal_in_projected_context": derived_illegal,
            "answered_rows": len(answered_records),
            "paired_rows_active": len(paired_active),
            "paired_rows_v2": len(paired_v2),
            "paired_rows_all_references": len(paired_all),
        },
        "validation_read": read_evidence,
        "test_scan": test_scan,
        "inputs": {
            "protocol": {
                "path": _relative(PROTOCOL_PATH),
                "sha256": sha256_file(PROTOCOL_PATH),
                "canonical_payload_sha256": canonical_hash(
                    json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))
                ),
            },
            "dataset": {"path": _relative(DATASET_PATH), "sha256": sha256_file(DATASET_PATH)},
            "dataset_manifest": {
                "path": _relative(DATASET_MANIFEST_PATH),
                "sha256": sha256_file(DATASET_MANIFEST_PATH),
            },
            "candidate": {
                "path": _relative(CANDIDATE_PATH),
                "sha256": sha256_file(CANDIDATE_PATH),
                "canonical_payload_sha256": candidate["canonical_payload_sha256"],
                "architecture": candidate["architecture"],
                "candidate_id": "generalized-adverse-response-candidate-v1",
            },
            "alternate_candidate": {
                "path": _relative(ALTERNATE_CANDIDATE_PATH),
                "sha256": sha256_file(ALTERNATE_CANDIDATE_PATH),
                "canonical_payload_sha256": alternate["canonical_payload_sha256"],
                "architecture": alternate["architecture"],
            },
            "active_model_a_v5": {
                "path": _relative(ACTIVE_MODEL_A_PATH),
                "sha256": active_after,
                "unchanged_during_evaluation": active_before == active_after,
            },
            "model_a_sizing_aware_v2_352": {
                "fit_path": _relative(ISSUE352_FIT_PATH),
                "fit_sha256": sha256_file(ISSUE352_FIT_PATH),
                "validation_path": _relative(ISSUE352_VALIDATION_PATH),
                "validation_sha256": sha256_file(ISSUE352_VALIDATION_PATH),
                "candidate_sha256": EXPECTED_ISSUE352_CANDIDATE_SHA256,
                "validation_evidence_sha256": EXPECTED_ISSUE352_VALIDATION_EVIDENCE_SHA256,
                "test_consumed": False,
            },
            "ood_calibration_report": {
                "path": _relative(OOD_REPORT_PATH),
                "sha256": sha256_file(OOD_REPORT_PATH),
                "calibration_canonical_payload_sha256": calibration.get(
                    "canonical_payload_sha256"
                ),
            },
            "fit_report": {"path": _relative(FIT_REPORT_PATH), "sha256": sha256_file(FIT_REPORT_PATH)},
            "train_cv_report": {"path": _relative(CV_REPORT_PATH), "sha256": sha256_file(CV_REPORT_PATH)},
            "raise_sizing_report": {
                "path": _relative(SIZING_REPORT_PATH),
                "sha256": sha256_file(SIZING_REPORT_PATH),
            },
        },
        "candidate": {
            "candidate_id": "generalized-adverse-response-candidate-v1",
            "architecture": candidate["architecture"],
            "canonical_payload_sha256": candidate["canonical_payload_sha256"],
            "status": "CANDIDATE_ONLY_NOT_ACTIVE",
        },
        "prior": {action: _round(prior[action]) for action in ACTIONS},
        "metrics": {
            "primary": {
                "name": "multiclass_log_loss",
                "unit": "bits_per_decision",
                "direction": "lower_is_better",
                "epsilon_clip": PROBABILITY_FLOOR,
                "paired_unit": "hand_id",
                "values": {
                    label: model_metrics[label]["log_loss_bits_per_decision"]
                    for label in MODEL_LABELS
                },
                "per_model": model_metrics,
            },
            "brier_score": {
                label: model_metrics[label]["brier_score"] for label in MODEL_LABELS
            },
            "accuracy": {label: model_metrics[label]["accuracy"] for label in MODEL_LABELS},
            "expected_calibration_error": {
                "method": "equal_count_reliability_bins",
                "bins_per_action_class": CALIBRATION_BINS,
                "minimum_bin_support_for_a_claim": CALIBRATION_MINIMUM_BIN_SUPPORT,
                "global": global_calibration,
                "detail": calibration_detail,
                "frozen_ceiling_comparison_on_paired_support": {
                    "support": "paired_active_model_a_v5",
                    "rows": paired_candidate_ece["pooled_support_rows"],
                    "candidate_ece": _round(ece, 12),
                    "active_ece": _round(active_ece, 12),
                    "delta_vs_active": _round(ece_delta, 12),
                },
            },
            "coverage": coverage_block,
            "strata": strata_block,
            "by_family": by_family_block,
            "sizing": {
                "criteria_id": "SIZING_NOT_INFERIOR_TO_FROZEN_TRAIN_EVIDENCE",
                "gate": False,
                "note": (
                    "the frozen protocol defines the raise-sizing criterion against the pinned "
                    "TRAIN evidence; the candidate's frozen sizing channel is exercised inside "
                    "the discrete predictions (a gain is applied to the RAISE/JAM branches of "
                    "every scored row).  The VALIDATION sizing numbers below are diagnostic only "
                    "and are not an admission gate, so no size threshold is relaxed or invented "
                    "after the read"
                ),
                "frozen_train_evidence": {
                    "path": _relative(SIZING_REPORT_PATH),
                    "sha256": sha256_file(SIZING_REPORT_PATH),
                    "rows": 7813,
                    "scored": 7639,
                    "fail_closed": 174,
                    "nll_bits_per_sizing": 2.683351,
                    "nll_gain_vs_uniform_bits": 3.380691,
                    "crps_bb": 4.702839,
                    "pit_max_abs_bin_error": 0.233682,
                    "illegal_generated_rate": 0.0,
                },
                "validation_diagnostic": {
                    "not_an_admission_gate": True,
                    "rows": sizing_diagnostic["rows"],
                    "scored": sizing_diagnostic["scored"],
                    "fail_closed": sizing_diagnostic["fail_closed"],
                    "nll_bits_per_sizing": _round(
                        sizing_diagnostic["nll_bits_per_sizing"]
                    ),
                    "nll_gain_vs_uniform_bits": _round(
                        sizing_diagnostic["nll_gain_vs_uniform_bits"]
                    ),
                    "crps_bb": _round(sizing_diagnostic["crps_bb"]),
                    "pit_max_abs_bin_error": _round(
                        sizing_diagnostic["calibration"].get("pit_max_abs_bin_error")
                    ),
                    "illegal_generated_rate": _round(
                        sizing_diagnostic["illegal_generated_rate"]
                    ),
                },
            },
        },
        "comparisons": comparisons,
        "non_inferiority": non_inferiority,
        "gates": {gate["id"]: gate for gate in gates},
        "gate": {
            "rule_id": "FROZEN_TEN_CRITERIA_ADMISSION",
            "criteria_total": len(gates),
            "criteria_passed": len(passed),
            "all_gates_pass": all_gates_pass,
            "passed": passed,
            "failed": failed,
        },
        "outcome": outcome,
        "decision": decision,
        "outcome_rule": (
            "ADMIT_GENERALIZED_RESPONSE_MODEL only when every frozen gate passes; otherwise "
            "RETAIN_REFERENCE_GENERALIZATION_INSUFFICIENT"
        ),
        "publication": {
            "result_path": "analysis/issue421_generalized_response/VALIDATION_RESULT.json",
            "decision_path": "analysis/issue421_generalized_response/DECISION.json",
            "declared_protocol_result_path": (
                "analysis/issue421_generalized_response/validation/VALIDATION_RESULT.json"
            ),
            "declared_result_locations_present": guard_evidence[
                "declared_result_locations_present"
            ],
            "reason": (
                "the protocol's VALIDATION_ORDER_GUARD fails closed as soon as a fenced result "
                "exists at its declared locations, which would make the frozen protocol no "
                "longer re-verifiable by tools/training/freeze_generalized_validation_protocol.py "
                "--check.  The T8 terminal evidence is therefore published beside the protocol at "
                "the paths named by the T8 scope, and the declared locations stay empty so the "
                "freeze remains checkable.  The order guard is still re-run before the read."
            ),
        },
        "active_pointer_mutated": False,
        "active_pointer_mutation": False,
        "automatic_promotion": "FORBIDDEN",
        "reported_reference_metrics": {
            "active_model_a_v5": {
                "path": _relative(ACTIVE_MODEL_A_PATH),
                "sha256": active_after,
                "present": True,
                "mean_dropped_non_response_mass": _round(active_dropped / total_rows)
                if total_rows
                else None,
                "exact_match_rows": active_exact,
                "matched_rows": len(paired_active),
            },
            "model_a_sizing_aware_candidate_v2": {
                "candidate_sha256": EXPECTED_ISSUE352_CANDIDATE_SHA256,
                "present": True,
                "matched_rows": len(paired_v2),
                "answered_rows_without_v2_support": len(answered_records) - len(paired_v2),
            },
            "candidate_generalized": {
                "canonical_payload_sha256": candidate["canonical_payload_sha256"],
                "present": True,
            },
        },
    }

    decision_payload = _decision_payload(result)
    return result, decision_payload


def _decision_payload(result: Mapping[str, Any]) -> dict[str, Any]:
    gates = list(result["gates"].values())
    failed = [gate["id"] for gate in gates if not gate["passed"]]
    passed = [gate["id"] for gate in gates if gate["passed"]]
    admitted = result["decision"] == DECISION_ADMIT
    if admitted:
        rationale = (
            "all "
            f"{len(gates)} frozen admission criteria hold on the one-shot VALIDATION "
            "evaluation: the candidate is not inferior to the fit global prior, the alternate "
            "hierarchical empirical-Bayes architecture and the active Model A v5 reference, "
            "clears the coverage floor and stays inside the frozen calibration ceiling"
        )
    else:
        rationale = (
            "the candidate fails "
            + ", ".join(failed)
            + " on the one-shot VALIDATION evaluation; the active Model A reference is retained "
            "and the generalization evidence is insufficient for admission"
        )
    return {
        "schema": DECISION_SCHEMA,
        "issue": 421,
        "terminal": True,
        "decision": result["decision"],
        "protocol_outcome": result["outcome"],
        "rationale": rationale,
        "decided_at": (result.get("protocol") or {}).get("frozen_at"),
        "split": "VALIDATION",
        "criteria_total": len(gates),
        "criteria_passed": len(passed),
        "passed_gates": passed,
        "failed_gates": failed,
        "gates": gates,
        "candidate": result["candidate"],
        "references": {
            "active_model_a_v5": {
                "path": result["inputs"]["active_model_a_v5"]["path"],
                "sha256": result["inputs"]["active_model_a_v5"]["sha256"],
                "role": "ACTIVE_MODEL_A_POINTER",
            },
            "model_a_sizing_aware_candidate_v2_352": {
                "candidate_sha256": EXPECTED_ISSUE352_CANDIDATE_SHA256,
                "validation_evidence_sha256": EXPECTED_ISSUE352_VALIDATION_EVIDENCE_SHA256,
                "role": "#352_ADMITTED_MODEL_A_CANDIDATE",
            },
            "candidate_generalized": {
                "canonical_payload_sha256": result["candidate"]["canonical_payload_sha256"],
                "architecture": result["candidate"]["architecture"],
                "role": "#421_GENERALIZED_RESPONSE_CANDIDATE",
            },
        },
        "comparisons_present": sorted(result["comparisons"].keys()),
        "comparisons": result["comparisons"],
        "metrics": {
            "log_loss_bits_per_decision": result["metrics"]["primary"]["values"],
            "brier_score": result["metrics"]["brier_score"],
            "expected_calibration_error": result["metrics"][
                "expected_calibration_error"
            ]["global"],
            "coverage": {
                "total": result["metrics"]["coverage"]["coverage"],
                "abstain_rate": result["metrics"]["coverage"]["abstain_rate"],
                "answered_decisions": result["metrics"]["coverage"]["answered_decisions"],
                "distinct_hands_answered": result["metrics"]["coverage"][
                    "distinct_hands_answered"
                ],
                "limiters_vs_iso": result["metrics"]["coverage"]["limiters_vs_iso"],
            },
            "strata": result["metrics"]["strata"]["share"],
        },
        "active_pointer_mutated": False,
        "active_model_pointer_mutation": False,
        "automatic_promotion": "FORBIDDEN",
        "validation_consumed": True,
        "validation_reads": 1,
        "test_consumed": False,
        "test_authorized": False,
        "downstream": (
            "only an admitted outcome may be consumed by #367; a retained candidate leaves the "
            "active Model A pointer unchanged and authorizes no #367 ISO EV run, no support-grid "
            "extension and no provider wiring"
        ),
        "issue367_authorized": admitted,
        "rollback": (
            "no production state was mutated: the terminal decision is a new evidence artifact "
            "and can be withdrawn by reverting this commit; the active Model A pointer was never "
            "written"
        ),
        "validation_result_path": _relative(RESULT_PATH),
        "publication": {
            "declared_protocol_result_path": result["publication"][
                "declared_protocol_result_path"
            ],
            "declared_result_locations_present": result["publication"][
                "declared_result_locations_present"
            ],
            "note": "the protocol's declared fenced location is intentionally empty; the terminal "
            "evidence lives beside the protocol so the freeze stays re-verifiable",
        },
    }


# ---------------------------------------------------------------------------
# persistence and checking
# ---------------------------------------------------------------------------


def persist(result: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    result_body = {key: value for key, value in result.items() if key != "canonical_payload_sha256"}
    result_canonical = canonical_hash(result_body)
    result["canonical_payload_sha256"] = result_canonical
    decision["validation_result_canonical_payload_sha256"] = result_canonical

    result_bytes = serialize(result)
    result_digest = hashlib.sha256(result_bytes).hexdigest()
    decision["validation_result_sha256"] = result_digest

    decision_body = {key: value for key, value in decision.items() if key != "canonical_payload_sha256"}
    decision_canonical = canonical_hash(decision_body)
    decision["canonical_payload_sha256"] = decision_canonical
    decision_bytes = serialize(decision)
    decision_digest = hashlib.sha256(decision_bytes).hexdigest()

    RESULT_PATH.write_bytes(result_bytes)
    RESULT_DIGEST_PATH.write_text(
        f"{result_digest}  VALIDATION_RESULT.json\n"
        f"# canonical_payload_sha256 {result_canonical}\n"
        f"# decision {result['decision']}\n"
    )
    DECISION_PATH.write_bytes(decision_bytes)
    DECISION_DIGEST_PATH.write_text(
        f"{decision_digest}  DECISION.json\n"
        f"# canonical_payload_sha256 {decision_canonical}\n"
        f"# decision {decision['decision']}\n"
    )
    return {
        "validation_result_path": _relative(RESULT_PATH),
        "validation_result_sha256": result_digest,
        "validation_result_canonical_payload_sha256": result_canonical,
        "decision_path": _relative(DECISION_PATH),
        "decision_sha256": decision_digest,
        "decision_canonical_payload_sha256": decision_canonical,
        "decision": decision["decision"],
    }


def check() -> int:
    """Verify the persisted artifacts without opening VALIDATION again."""
    problems: list[str] = []
    for path in (RESULT_PATH, DECISION_PATH):
        if not path.is_file():
            problems.append(f"missing {_relative(path)}")
    if problems:
        print(json.dumps({"status": "MISMATCH", "problems": problems}, indent=2))
        return 1

    result = json.loads(RESULT_PATH.read_text(encoding="utf-8"))
    decision = json.loads(DECISION_PATH.read_text(encoding="utf-8"))

    if result.get("schema") != RESULT_SCHEMA:
        problems.append("unexpected VALIDATION_RESULT schema")
    if decision.get("schema") != DECISION_SCHEMA:
        problems.append("unexpected DECISION schema")
    if result.get("test_consumed") is not False or decision.get("test_consumed") is not False:
        problems.append("a persisted artifact claims a TEST read")
    if result.get("active_pointer_mutated") is not False:
        problems.append("VALIDATION_RESULT claims the active pointer mutated")
    if decision.get("active_pointer_mutated") is not False:
        problems.append("DECISION claims the active pointer mutated")

    body = {key: value for key, value in result.items() if key != "canonical_payload_sha256"}
    if canonical_hash(body) != result.get("canonical_payload_sha256"):
        problems.append("VALIDATION_RESULT canonical payload digest mismatch")
    decision_body = {
        key: value for key, value in decision.items() if key != "canonical_payload_sha256"
    }
    if canonical_hash(decision_body) != decision.get("canonical_payload_sha256"):
        problems.append("DECISION canonical payload digest mismatch")

    result_digest = sha256_file(RESULT_PATH)
    if decision.get("validation_result_sha256") != result_digest:
        problems.append("DECISION does not pin the current VALIDATION_RESULT bytes")
    if RESULT_DIGEST_PATH.is_file() and not RESULT_DIGEST_PATH.read_text().startswith(
        result_digest + "  "
    ):
        problems.append("VALIDATION_RESULT .sha256 sidecar mismatch")
    if DECISION_DIGEST_PATH.is_file() and not DECISION_DIGEST_PATH.read_text().startswith(
        sha256_file(DECISION_PATH) + "  "
    ):
        problems.append("DECISION .sha256 sidecar mismatch")

    gates = list(result["gates"].values())
    failed = [gate["id"] for gate in gates if not gate["passed"]]
    all_gates_pass = not failed
    expected_outcome = PROTOCOL_OUTCOME_ADMIT if all_gates_pass else PROTOCOL_OUTCOME_RETAIN
    expected_decision = DECISION_ADMIT if all_gates_pass else DECISION_RETAIN
    if result.get("outcome") != expected_outcome:
        problems.append("outcome does not follow from the persisted gates")
    if decision.get("decision") != expected_decision:
        problems.append("terminal decision does not follow from the persisted gates")
    if result.get("decision") != decision.get("decision"):
        problems.append("DECISION and VALIDATION_RESULT disagree on the decision")
    if decision.get("protocol_outcome") != result.get("outcome"):
        problems.append("DECISION and VALIDATION_RESULT disagree on the protocol outcome")
    if sha256_file(PROTOCOL_PATH) != EXPECTED_PROTOCOL_BYTE_SHA256:
        problems.append("the frozen protocol bytes changed after the evaluation")
    if sha256_file(ACTIVE_MODEL_A_PATH) != EXPECTED_ACTIVE_MODEL_A_SHA256:
        problems.append("the active Model A v5 pointer changed after the evaluation")

    if problems:
        print(json.dumps({"status": "MISMATCH", "problems": problems}, indent=2))
        return 1
    print(
        json.dumps(
            {
                "status": "OK",
                "schema": RESULT_SCHEMA,
                "decision": decision["decision"],
                "protocol_outcome": result["outcome"],
                "criteria_passed": len(gates) - len(failed),
                "criteria_total": len(gates),
                "failed_gates": failed,
                "active_pointer_mutated": False,
                "test_consumed": False,
                "validation_result_sha256": result_digest,
            },
            indent=2,
        )
    )
    return 0


def self_check() -> int:
    scan = verify_no_test_loader()
    print(json.dumps({"status": "OK", "test_scan": scan}, indent=2))
    return 0


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--check",
        action="store_true",
        help="verify the persisted VALIDATION_RESULT/DECISION instead of re-running",
    )
    group.add_argument(
        "--self-check",
        action="store_true",
        help="run the static TEST-loader self-scan only",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.self_check:
        return self_check()
    if args.check:
        return check()
    result, decision = evaluate()
    publication = persist(result, decision)
    print(
        json.dumps(
            {
                "status": "WRITTEN",
                "decision": decision["decision"],
                "protocol_outcome": result["outcome"],
                "criteria_passed": result["gate"]["criteria_passed"],
                "criteria_total": result["gate"]["criteria_total"],
                "failed_gates": result["gate"]["failed"],
                "coverage": result["metrics"]["coverage"]["coverage"],
                "active_pointer_mutated": False,
                "test_consumed": False,
                **publication,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""#421 guard: TRAIN-only fragmentation audit and representation verdicts.

Covers the four acceptance criteria of the task:

* the report is TRAIN-only: ``validation_consumed=false`` and
  ``test_consumed=false``, and a VALIDATION/TEST row fails closed;
* every audited dimension carries a keep/aggregate/remove verdict with an
  evidence-backed justification built from measured predictive gain and/or
  fragmentation cost;
* fragmentation is quantified (level cardinality, effective cardinality,
  low-support shares, induced joint-cell growth) and the low-support zones are
  listed;
* the persisted report artifact is internally consistent (its ``report_hash``
  recomputes) and readable.

The expensive full-corpus re-projection is exercised by
``tools/training/audit_generalized_response_features.py`` itself; this suite runs
deterministic synthetic fixtures plus read-only checks of the persisted report.
"""
from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.training import audit_generalized_response_features as tool  # noqa: E402
from tools.training.build_generalized_response_dataset import (  # noqa: E402
    RESPONSE_ACTIONS,
    ROW_FIELDS,
    TestSplitForbidden,
    iter_response_rows,
    stable_hash,
)

POSITIONS = ("LJ", "HJ", "CO", "BTN", "SB", "BB")
FAMILIES = ("UNOPENED", "VS_RFI", "VS_LIMPERS", "VS_ISO")
FAMILY_ACTION = {"UNOPENED": "RAISE", "VS_RFI": "FOLD", "VS_LIMPERS": "CALL", "VS_ISO": "JAM"}
FAMILY_TO_CALL = {"UNOPENED": 1.0, "VS_RFI": 2.5, "VS_LIMPERS": 0.5, "VS_ISO": 6.0}
VERDICTS = ("KEEP", "AGGREGATE", "REMOVE")
VERDICT_FR = {"KEEP": "conserv\u00e9e", "AGGREGATE": "agr\u00e9g\u00e9e", "REMOVE": "supprim\u00e9e"}
REPORT_PATH = ROOT / "analysis/issue421_generalized_response/GENERALIZED_RESPONSE_DATASET_REPORT.json"


def noise(hand: int, modulus: int) -> int:
    """Deterministic pseudo-random level that is independent of the fixture."""
    digest = hashlib.sha256(("noise-" + str(hand)).encode()).hexdigest()
    return int(digest[:8], 16) % modulus


def row(
    hand: int,
    *,
    family: str = "UNOPENED",
    actor: str = "LJ",
    action: str = "FOLD",
    to_call: float = 1.0,
    pot: float = 1.5,
    stack: float = 100.0,
    limpers: int = 0,
    callers: int = 0,
    raise_level: int = 0,
    aggressor: str | None = None,
    live: tuple[str, ...] = POSITIONS,
    table_size: int = 6,
    split: str = "TRAIN",
) -> dict:
    """One contract-shaped public response row."""
    pot_odds = round(to_call / (pot + to_call), 6) if (pot + to_call) > 0 else None
    price_to_pot = round(to_call / pot, 6) if pot > 0 else None
    return {
        "hand_id": str(hand),
        "split": split,
        "table_size": table_size,
        "family": family,
        "actor_position": actor,
        "aggressor_position": aggressor,
        "limper_count": limpers,
        "caller_count": callers,
        "live_positions": list(live),
        "raise_level": raise_level,
        "to_call_bb": to_call,
        "pot_before_bb": pot,
        "pot_odds": pot_odds,
        "price_to_pot": price_to_pot,
        "effective_stack_bb": stack,
        "target_total_bb": None,
        "observed_sizing_bb": None,
        "action": action,
    }


def signal_rows(count: int = 3000) -> list[dict]:
    """Family drives the action; ``raise_level`` is unrelated high-cardinality noise."""
    rows = []
    for hand in range(count):
        family = FAMILIES[hand % len(FAMILIES)]
        rows.append(
            row(
                hand,
                family=family,
                actor=POSITIONS[hand % len(POSITIONS)],
                action=FAMILY_ACTION[family],
                to_call=FAMILY_TO_CALL[family],
                pot=1.5,
                stack=100.0,
                limpers=0,
                callers=0,
                raise_level=noise(hand, 400),
            )
        )
    return rows


def aggregation_rows() -> list[dict]:
    """A strong ``limper_count`` effect with two rare levels that must be merged."""
    buckets = [(0, 900, "RAISE"), (1, 600, "CALL"), (2, 400, "FOLD"), (3, 60, "JAM"),
               (4, 25, "FOLD"), (5, 15, "FOLD")]
    rows: list[dict] = []
    hand = 0
    for limpers, size, action in buckets:
        for _ in range(size):
            rows.append(
                row(
                    hand,
                    family="VS_LIMPERS",
                    actor=POSITIONS[hand % len(POSITIONS)],
                    action=action,
                    to_call=1.0,
                    pot=2.5,
                    stack=100.0,
                    limpers=limpers,
                )
            )
            hand += 1
    return rows


def assert_scope(report: dict, *, label: str) -> None:
    scope = report["scope"]
    assert scope["split_consumed"] == "TRAIN", label
    assert scope["validation_consumed"] is False, label
    assert scope["test_consumed"] is False, label
    assert scope["validation_decisions_read"] == 0, label
    assert scope["test_decisions_read"] == 0, label
    assert scope["refused_splits"] == ["TEST"], label
    assert scope["model_fitted"] is False and scope["optimization_performed"] is False, label
    assert report["holdout_protocol"]["validation_used"] is False, label
    assert report["holdout_protocol"]["test_used"] is False, label
    assert report["holdout_protocol"]["hand_disjoint"] is True, label


def assert_verdicts(report: dict) -> None:
    names = [dimension["name"] for dimension in report["dimensions"]]
    assert names == list(tool.DIMENSION_ORDER), names
    for dimension in report["dimensions"]:
        name = dimension["name"]
        assert dimension["verdict"] in VERDICTS, (name, dimension["verdict"])
        assert dimension["verdict_fr"] == VERDICT_FR[dimension["verdict"]], name
        assert dimension["justification"], name
        assert all(isinstance(line, str) and line for line in dimension["justification"]), name
        evidence = dimension["evidence"]
        gain = evidence["predictive_gain_bits_per_decision"]
        assert gain["effective_remove_threshold_bits"] > 0, name
        assert gain["raw"] is not None, name
        assert evidence["fragmentation"]["raw_distinct_levels"] >= 1, name
        assert evidence["support_thresholds"]["min_support_rows"] == tool.MIN_SUPPORT_ROWS, name
        raw = dimension["raw"]
        assert raw["fragmentation"]["distinct_levels"] == raw["distinct_levels"], name
        assert raw["levels"]["entries"], name
        if dimension["aggregation"] is not None:
            aggregated = dimension["aggregation"]
            assert aggregated["distinct_levels"] <= raw["distinct_levels"], name
        assert dimension["recommended_candidate_id"], name


def assert_fragmentation(report: dict, *, require_zones: bool = False) -> None:
    fragmentation = report["fragmentation"]
    raw = fragmentation["raw_full_representation"]
    recommended = fragmentation["recommended_representation"]
    assert raw["cells_total"] >= 1
    assert raw["rows_total"] == report["accounting"]["train_response_rows"]
    assert 0.0 <= raw["rows_share_in_low_support_cells"] <= 1.0
    assert recommended["cells_total"] <= raw["cells_total"]
    assert recommended["rows_share_in_low_support_cells"] <= raw["rows_share_in_low_support_cells"]
    removed = {d["name"] for d in report["dimensions"] if d["verdict"] == "REMOVE"}
    assert fragmentation["removed_dimensions"] == sorted(removed, key=tool.DIMENSION_ORDER.index)
    assert set(recommended["dimensions"]) == set(tool.DIMENSION_ORDER) - removed
    assert len(fragmentation["induced_by_dimension"]) == len(tool.DIMENSION_ORDER) - len(removed)
    assert fragmentation["induced_by_dimension"][0]["cells_before"] == 0
    assert fragmentation["induced_by_dimension"][-1]["cells_after"] == recommended["cells_total"]
    for step in fragmentation["induced_by_dimension"]:
        assert step["dimension"] in set(tool.DIMENSION_ORDER) - removed
        assert step["cells_after"] >= step["cells_before"]
        assert 0.0 <= step["rows_share_in_low_support_cells_after"] <= 1.0

    zones = report["low_support_zones"]
    assert zones["cells_total"] == recommended["low_support_cells"]
    assert len(zones["per_dimension"]) == len(tool.DIMENSION_ORDER)
    if zones["cells_total"]:
        assert zones["cells"], "low-support zones must be listed when they exist"
        assert zones["cells_truncated"] is (zones["cells_total"] > len(zones["cells"]))
    else:
        assert zones["cells"] == []
    if require_zones:
        assert zones["cells_total"] > 0, "the persisted report must expose low-support zones"
    for cell in zones["cells"]:
        assert cell["observations"] < tool.MIN_SUPPORT_ROWS, cell
        assert cell["support_tier"] == "SPARSE", cell
        assert set(cell["actions"]) == set(RESPONSE_ACTIONS), cell
        assert set(cell["levels"]) == set(tool.DIMENSION_ORDER) - removed, cell
    for dimension in zones["per_dimension"]:
        assert dimension["levels_below_min_support"] >= 0
        assert isinstance(dimension["examples"], list)


def check_persisted_report() -> None:
    assert REPORT_PATH.is_file(), f"missing persisted report: {REPORT_PATH}"
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    assert report["schema"] == tool.SCHEMA
    assert_scope(report, label="persisted")
    assert_verdicts(report)
    assert_fragmentation(report, require_zones=True)
    assert report["population_id"] == tool.POPULATION_ID
    assert report["accounting"]["train_response_rows"] > 0
    assert report["verdict_summary"]["counts"] == {
        verdict: len(report["verdict_summary"][verdict]) for verdict in VERDICTS
    }
    by_axis = report["verdict_summary"]["by_axis"]
    assert set(by_axis) == {"FAMILY", "POSITION", "SIZING", "STACK"}, sorted(by_axis)
    assert sorted(
        name
        for axis in by_axis.values()
        for verdict in VERDICTS
        for name in axis[verdict]
    ) == sorted(tool.DIMENSION_ORDER)
    assert sorted(
        report["verdict_summary"]["KEEP"]
        + report["verdict_summary"]["AGGREGATE"]
        + report["verdict_summary"]["REMOVE"]
    ) == sorted(tool.DIMENSION_ORDER)
    recomputed = stable_hash({k: v for k, v in report.items() if k != "report_hash"})
    assert recomputed == report["report_hash"], "persisted report_hash does not recompute"
    provenance = report["provenance"]
    assert provenance["validation_hands_consumed"] == 0
    assert provenance["test_hands_consumed"] == 0
    assert provenance["train_hand_ids_fingerprint_sha256"] == (
        report["dataset_artifact"]["train_split"]["hand_ids_fingerprint_sha256"]
    )
    assert report["dataset_artifact"]["validation_rows_read"] == 0
    assert report["dataset_artifact"]["test_rows_read"] == 0
    assert report["dataset_artifact"]["manifest_validation_block_consumed"] is False
    encoded = json.dumps(report, sort_keys=True)
    assert '"validation_consumed": false' in encoded
    assert '"test_consumed": false' in encoded


def expect_assertion(rows: list[dict], needle: str) -> None:
    try:
        tool.analyze_rows(rows)
    except AssertionError as exc:
        assert needle in str(exc), (needle, str(exc))
    else:
        raise AssertionError(f"audit must fail closed on {needle!r}")


def main() -> None:
    # --- 1. structural contract on a synthetic TRAIN fixture -----------------
    report = tool.analyze_rows(signal_rows(), {"fixture": "synthetic-signal"})
    assert report["schema"] == tool.SCHEMA
    assert_scope(report, label="synthetic")
    assert_verdicts(report)
    assert_fragmentation(report)
    assert report["accounting"]["train_response_rows"] == 3000
    assert report["accounting"]["train_distinct_hands"] == 3000
    assert report["accounting"]["fit_rows"] + report["accounting"]["holdout_rows"] == 3000
    assert report["observed_sizing_outcomes"]["excluded_from_predictive_dimensions"] is True
    assert set(tool.OUTCOME_DIMENSIONS) - set(tool.DIMENSION_ORDER) == set(tool.OUTCOME_DIMENSIONS)
    assert report["semantics"]["verdict_labels_fr"] == VERDICT_FR

    # --- 2. deterministic and order independent ------------------------------
    reversed_report = tool.analyze_rows(list(reversed(signal_rows())), {"fixture": "synthetic-signal"})
    assert reversed_report == report, "the report must be row-order independent"
    assert tool.canonical_report_bytes(reversed_report) == tool.canonical_report_bytes(report)
    assert json.loads(json.dumps(report))["report_hash"] == report["report_hash"]

    # --- 3. verdict sensitivity ---------------------------------------------
    family = tool.dimension_by_name(report, "family")
    assert family["verdict"] == "KEEP", family["justification"]
    assert family["raw"]["predictive_gain"]["held_out_gain_bits"] > 0.1

    noise_dimension = tool.dimension_by_name(report, "raise_level")
    assert noise_dimension["verdict"] == "REMOVE", noise_dimension["justification"]
    assert noise_dimension["raw"]["fragmentation"]["distinct_levels"] > 64

    constant = tool.dimension_by_name(report, "table_size")
    assert constant["verdict"] == "REMOVE", constant["justification"]
    assert constant["raw"]["fragmentation"]["distinct_levels"] == 1
    assert constant["raw"]["predictive_gain"]["held_out_gain_bits"] == 0.0

    aggregating = tool.analyze_rows(aggregation_rows(), {"fixture": "synthetic-limbers"})
    limper = tool.dimension_by_name(aggregating, "limper_count")
    assert limper["verdict"] == "AGGREGATE", limper["justification"]
    assert limper["aggregation_retains_measured_gain"] is True
    assert limper["aggregation"]["distinct_levels"] < limper["raw"]["fragmentation"]["distinct_levels"]
    assert limper["raw"]["fragmentation"]["levels_below_min_support"] >= 1
    assert limper["aggregation"]["fragmentation"]["levels_below_min_support"] == 0
    assert limper["recommended_candidate_id"] in {
        "RAW__MERGE_BELOW_MIN_SUPPORT",
        "RAW__MERGE_BELOW_STRONG_SUPPORT",
        "RAW__TOP_4_LEVELS",
        "RAW__TOP_8_LEVELS",
    }

    # --- 4. fail-closed boundaries ------------------------------------------
    test_rows = copy.deepcopy(signal_rows()[:40])
    test_rows[0]["split"] = "TEST"
    expect_assertion(test_rows, "TEST")

    validation_rows = copy.deepcopy(signal_rows()[:40])
    validation_rows[0]["split"] = "VALIDATION"
    expect_assertion(validation_rows, "non-TRAIN")

    missing_field = copy.deepcopy(signal_rows()[:40])
    missing_field[0].pop("effective_stack_bb")
    expect_assertion(missing_field, "missing dataset fields")

    bad_action = copy.deepcopy(signal_rows()[:40])
    bad_action[0]["action"] = "CHECK"
    expect_assertion(bad_action, "action outside")

    try:
        iter_response_rows([], "TEST")
    except TestSplitForbidden:
        pass
    else:
        raise AssertionError("the reused dataset projector must refuse TEST")

    try:
        tool.analyze_rows([])
    except ValueError:
        pass
    else:
        raise AssertionError("an empty TRAIN corpus must be refused")

    # --- 5. persisted report artifact ---------------------------------------
    check_persisted_report()

    print("TRAIN-only generalized response fragmentation audit contract: PASS")


if __name__ == "__main__":
    main()

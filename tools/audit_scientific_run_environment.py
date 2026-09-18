#!/usr/bin/env python3
"""Read-only audit of environment identity coverage for current scientific run families."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "poker-scientific-run-environment-audit/v1"

TARGETS = [
    {"id":"model_a","category":"Model A","path":"training/runs/20260915_model_a_postflop_refit_v1/PROTOCOL.json","future_integration":"Future Model A PROTOCOL/RESULT manifests: persist top-level environment_identity before execution and carry the same identity_sha256 into result provenance.","historical_policy":"GRANDFATHERED_IMMUTABLE","priority":"HIGH"},
    {"id":"model_b","category":"Model B","path":"training/runs/20260919_model_b_response_to_price_v1/RESULT.json","future_integration":"Future Model B PROTOCOL and RESULT: top-level environment_identity; result must match the frozen protocol identity_sha256.","historical_policy":"GRANDFATHERED_IMMUTABLE","priority":"HIGH"},
    {"id":"hero_pfpc","category":"Hero strategy / PFPC","path":"training/runs/20260918_hero_preflop_unopened_5pos_pfpc_v1/RESULT.json","future_integration":"Future Hero/PFPC run root RESULT/VALIDATION and source-run descriptor: bind one environment_identity for the complete generated evidence set.","historical_policy":"GRANDFATHERED_IMMUTABLE","priority":"HIGH"},
    {"id":"full_hand_arena","category":"Full-hand arena","path":"training/full_hand/FULL_HAND_EVALUATION_PROTOCOL_20260915.json","future_integration":"Future frozen arena protocol records environment_identity.identity_sha256 before execution; generated arena evidence persists the full fragment.","historical_policy":"GRANDFATHERED_IMMUTABLE_PROTOCOL","priority":"HIGH"},
    {"id":"validation","category":"Validation","path":"training/runs/20260917_preflop_strategy_validation_support_closed_zero_exposure/RESULT.json","future_integration":"Future VALIDATION/TEST execution RESULT: top-level environment_identity and identity_sha256 inside frozen_run_identity/provenance.","historical_policy":"GRANDFATHERED_IMMUTABLE","priority":"HIGH"},
    {"id":"promotion","category":"Promotion gate","path":"training/PROMOTION_GATE_CONTRACT.json","future_integration":"After activation, promotion evidence requires a validated environment_identity for every new scientific result; the historical gate contract itself is not rewritten.","historical_policy":"GRANDFATHERED_IMMUTABLE_CONTRACT","priority":"HIGH"},
    {"id":"prospective","category":"Prospective","path":"training/prospective/PROTOCOL.json","future_integration":"Next prospective protocol version adds environment_identity.identity_sha256 to precommit_identity and stores the full fragment in the future evaluation manifest/ledger entry.","historical_policy":"GRANDFATHERED_IMMUTABLE_PROTOCOL","priority":"HIGH"},
    {"id":"increment_cycle","category":"Other scientific run: incremental training cycle","path":"training/runs/20260912_population_increment_cycle/manifest.json","future_integration":"Future training-cycle manifest: top-level environment_identity before model fitting/evaluation.","historical_policy":"GRANDFATHERED_IMMUTABLE","priority":"MEDIUM"},
    {"id":"strategy_selection","category":"Other scientific run: strategy selection","path":"training/runs/20260913_strategy_candidate_v84/validation_selection.json","future_integration":"Future strategy-selection manifest: replace generic environment prose with top-level environment_identity plus any domain-specific environment fields.","historical_policy":"GRANDFATHERED_IMMUTABLE","priority":"MEDIUM"},
    {"id":"generic_template","category":"Generic run manifest template","path":"training/RUN_MANIFEST_TEMPLATE.json","future_integration":"After #108 release, extend the template/producer so every newly created scientific run carries environment_identity with policy REQUIRED.","historical_policy":"NOT_A_HISTORICAL_RUN","priority":"HIGH"},
]


def _contains_identity(value: Any) -> bool:
    if isinstance(value, dict):
        if "environment_identity" in value:
            return True
        return any(_contains_identity(v) for v in value.values())
    if isinstance(value, list):
        return any(_contains_identity(v) for v in value)
    return False


def build_audit(root: Path = ROOT) -> dict[str, Any]:
    root = root.resolve()
    rows = []
    missing_paths = []
    for target in TARGETS:
        path = root / target["path"]
        if not path.is_file():
            missing_paths.append(target["path"])
            present = False
        else:
            raw = path.read_text(encoding="utf-8")
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSON representative {target['path']}: {exc}") from exc
            present = _contains_identity(parsed)
        rows.append({**target, "environment_identity_present": present})
    return {
        "schema": SCHEMA,
        "policy": {
            "historical_runs": "IMMUTABLE_GRANDFATHERED_NO_REWRITE",
            "future_runs_after_activation": "ENVIRONMENT_IDENTITY_REQUIRED_FAIL_CLOSED",
            "current_scientific_effect": "NONE_INFRASTRUCTURE_ONLY",
        },
        "summary": {
            "targets": len(rows),
            "with_environment_identity": sum(row["environment_identity_present"] for row in rows),
            "without_environment_identity": sum(not row["environment_identity_present"] for row in rows),
            "missing_representatives": missing_paths,
        },
        "targets": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check", type=Path)
    args = parser.parse_args()
    audit = build_audit(args.root)
    if audit["summary"]["missing_representatives"]:
        print("ERROR: missing representative scientific manifests", file=sys.stderr)
        return 2
    text = json.dumps(audit, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if args.check:
        if not args.check.is_file() or args.check.read_text(encoding="utf-8") != text:
            print("ERROR: scientific environment audit is stale", file=sys.stderr)
            return 2
        print("scientific environment audit: OK")
        return 0
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
        print(args.output)
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

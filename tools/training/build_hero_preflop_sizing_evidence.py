#!/usr/bin/env python3
"""Freeze compact TRAIN-only preflop sizing evidence for one Hero context.

The large certified decision corpus is materialized once, then this tool selects
only the exact structural node needed by a frozen #107 Hero context.  The output
is small enough to fan out to many CI shards without re-reading source archives.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

from tools.simulation.model_a_continuation import ModelAContinuationPolicy
from tools.training import generate_hero_range_decisions as base
from tools.training.generate_certified_hero_range_decisions import observed_raise_targets

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = "poker-hero-preflop-sizing-evidence/v1"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build(
    *,
    spec: base.ContextSpec,
    policy: ModelAContinuationPolicy,
    decisions_path: Path,
    output_path: Path,
    code_sha: str,
) -> dict:
    state = base.build_context_state(spec)
    targets, support = observed_raise_targets(
        policy, state, spec.position, decisions_path
    )
    evidence = {
        "schema": SCHEMA,
        "population_id": spec.population_id,
        "context": spec.repository_context(),
        "context_id": spec.context_id,
        "code_sha": code_sha,
        "models": dict(policy.identity),
        "sizing_support": support,
        "legal_grid_targets_bb": targets,
        "selection": "TRAIN_ONLY_NO_VALIDATION_NO_TEST",
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return evidence


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--position", default="BTN", choices=list(base.DEFAULT_SEATS))
    p.add_argument("--spot", default="UNOPENED", choices=["UNOPENED", "VS_LIMPERS", "VS_RFI", "VS_RFI_CALLERS"])
    p.add_argument("--stack-bb", type=float, default=100.0)
    p.add_argument("--opener-position")
    p.add_argument("--caller-position")
    p.add_argument("--limper-position")
    p.add_argument("--open-to-bb", type=float, default=2.5)
    p.add_argument("--preflop-model", type=Path, default=base.DEFAULT_PREFLOP)
    p.add_argument("--postflop-model", type=Path, default=base.DEFAULT_POSTFLOP)
    p.add_argument("--continuation-overlay", type=Path, default=base.DEFAULT_OVERLAY)
    p.add_argument("--decisions", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--code-sha", default=os.environ.get("GITHUB_SHA", ""))
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if not str(args.code_sha).strip():
        raise SystemExit("--code-sha (or GITHUB_SHA) is required")
    spec = base.ContextSpec(
        position=args.position,
        effective_stack_bb=args.stack_bb,
        spot=args.spot,
        opener_position=args.opener_position,
        caller_position=args.caller_position,
        limper_position=args.limper_position,
        open_to_bb=args.open_to_bb,
    )
    policy = ModelAContinuationPolicy.from_paths(
        args.preflop_model, args.postflop_model, args.continuation_overlay
    )
    evidence = build(
        spec=spec,
        policy=policy,
        decisions_path=args.decisions,
        output_path=args.output,
        code_sha=str(args.code_sha),
    )
    print(json.dumps({
        "schema": evidence["schema"],
        "context_id": evidence["context_id"],
        "targets": evidence["legal_grid_targets_bb"],
        "support": evidence["sizing_support"]["observed_nonjam_raises"],
        "output_sha256": sha256_file(args.output),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

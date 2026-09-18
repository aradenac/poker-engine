#!/usr/bin/env python3
"""Finalize one persisted scientific cycle into the #113 release handoff.

This is the single release-routing command after a cycle decision exists:

* RETAIN / NO_OP / BLOCKED -> VERIFIED_NO_PUBLICATION;
* PROMOTE -> PREPARED, with all candidate/promotion/deployment identities frozen.

It deliberately performs no Git push, GitHub Release or Cloudflare deployment.
The canonical builders remain the authority for release-state validation.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.training.build_promote_release_handoff import (  # noqa: E402
    _promotion_authorized,
    build_prepared_promote_handoff,
)
from tools.training.build_release_handoff import (  # noqa: E402
    build_no_publication_handoff,
    derive_outcome,
    rel,
)
from tools.validate_release_handoff import DEFAULT_CONTRACT, load_json  # noqa: E402


def classify_release_outcome(decision: Mapping[str, Any]) -> str:
    """Return one unambiguous release outcome from the persisted cycle decision."""
    no_publication = derive_outcome(decision)
    promote = _promotion_authorized(decision)
    if promote and no_publication is not None:
        raise ValueError(
            "cycle decision is internally inconsistent: it both authorizes PROMOTE "
            f"and resolves to {no_publication}"
        )
    if promote:
        return "PROMOTE"
    if no_publication is not None:
        return no_publication
    raise ValueError(
        "cycle decision has no recognized terminal release outcome; expected "
        "PROMOTE, RETAIN, NO_OP or BLOCKED vocabulary"
    )


def _resolve(root: Path, value: Path) -> Path:
    return value.resolve() if value.is_absolute() else (root / value).resolve()


def _need_promote(value: Any, name: str) -> Any:
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ValueError(f"PROMOTE requires {name}")
    return value


def finalize_cycle_release(
    *,
    root: Path,
    population_id: str,
    cycle_run_id: str,
    cycle_decision_path: Path,
    snapshot: Path | None,
    snapshot_sha256: str | None,
    site_release_path: Path,
    population_registry_path: Path,
    source_commit_sha: str | None,
    reason: str | None,
    promotion_plan_path: Path | None,
    candidate_pack_path: Path | None,
    candidate_site_release_path: Path | None,
    expected_release_commit_sha: str | None,
    wrangler_config_path: Path,
    production_url: str | None,
    contract_path: Path = DEFAULT_CONTRACT,
) -> tuple[dict[str, Any], dict[str, Any]]:
    root = Path(root).resolve()
    cycle_decision_path = Path(cycle_decision_path).resolve()
    decision = load_json(cycle_decision_path)
    outcome = classify_release_outcome(decision)

    if outcome != "PROMOTE":
        selected_reason = (
            str(reason).strip()
            if reason is not None and str(reason).strip()
            else f"Cycle decision resolved to {outcome}; production identities remain unchanged."
        )
        return build_no_publication_handoff(
            root=root,
            population_id=population_id,
            cycle_run_id=cycle_run_id,
            cycle_decision_path=cycle_decision_path,
            snapshot=snapshot,
            snapshot_sha256=snapshot_sha256,
            site_release_path=site_release_path,
            population_registry_path=population_registry_path,
            source_commit_sha=source_commit_sha,
            outcome=outcome,
            reason=selected_reason,
            contract_path=contract_path,
        )

    promotion_plan_path = Path(_need_promote(promotion_plan_path, "--promotion-plan")).resolve()
    candidate_pack_path = Path(_need_promote(candidate_pack_path, "--candidate-pack")).resolve()
    candidate_site_release_path = Path(
        _need_promote(candidate_site_release_path, "--candidate-site-release")
    ).resolve()
    expected_release_commit_sha = str(
        _need_promote(expected_release_commit_sha, "--expected-release-commit-sha")
    )
    production_url = str(_need_promote(production_url, "--production-url"))

    return build_prepared_promote_handoff(
        root=root,
        population_id=population_id,
        cycle_run_id=cycle_run_id,
        cycle_decision_path=cycle_decision_path,
        snapshot=snapshot,
        snapshot_sha256=snapshot_sha256,
        site_release_path=site_release_path,
        population_registry_path=population_registry_path,
        source_commit_sha=source_commit_sha,
        promotion_plan_path=promotion_plan_path,
        candidate_pack_path=candidate_pack_path,
        candidate_site_release_path=candidate_site_release_path,
        expected_release_commit_sha=expected_release_commit_sha,
        wrangler_config_path=wrangler_config_path,
        production_url=production_url,
        contract_path=contract_path,
    )


def write_new_handoff(path: Path, document: Mapping[str, Any]) -> None:
    path = Path(path)
    if path.exists():
        raise FileExistsError(f"refusing to overwrite existing release handoff: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--population-id", required=True)
    parser.add_argument("--cycle-run-id", required=True)
    parser.add_argument("--cycle-decision", type=Path, required=True)
    snapshot = parser.add_mutually_exclusive_group(required=True)
    snapshot.add_argument("--snapshot", type=Path)
    snapshot.add_argument("--snapshot-sha256")
    parser.add_argument("--site-release", type=Path, default=Path("site/RELEASE.json"))
    parser.add_argument(
        "--population-registry",
        type=Path,
        default=Path("training/populations/registry.json"),
    )
    parser.add_argument("--source-commit-sha")
    parser.add_argument("--reason")
    parser.add_argument("--promotion-plan", type=Path)
    parser.add_argument("--candidate-pack", type=Path)
    parser.add_argument("--candidate-site-release", type=Path)
    parser.add_argument("--expected-release-commit-sha")
    parser.add_argument("--wrangler-config", type=Path, default=Path("wrangler.jsonc"))
    parser.add_argument("--production-url")
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--out", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.root.resolve()

    document, validation = finalize_cycle_release(
        root=root,
        population_id=args.population_id,
        cycle_run_id=args.cycle_run_id,
        cycle_decision_path=_resolve(root, args.cycle_decision),
        snapshot=None if args.snapshot is None else _resolve(root, args.snapshot),
        snapshot_sha256=args.snapshot_sha256,
        site_release_path=_resolve(root, args.site_release),
        population_registry_path=_resolve(root, args.population_registry),
        source_commit_sha=args.source_commit_sha,
        reason=args.reason,
        promotion_plan_path=None if args.promotion_plan is None else _resolve(root, args.promotion_plan),
        candidate_pack_path=None if args.candidate_pack is None else _resolve(root, args.candidate_pack),
        candidate_site_release_path=(
            None
            if args.candidate_site_release is None
            else _resolve(root, args.candidate_site_release)
        ),
        expected_release_commit_sha=args.expected_release_commit_sha,
        wrangler_config_path=_resolve(root, args.wrangler_config),
        production_url=args.production_url,
        contract_path=_resolve(root, args.contract),
    )
    output = _resolve(root, args.out)
    write_new_handoff(output, document)
    print(json.dumps({
        "handoff": rel(root, output),
        "outcome": document["outcome"],
        "state": document["state"],
        "delivered": validation["delivered"],
        "validation": validation,
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

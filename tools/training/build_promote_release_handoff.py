#!/usr/bin/env python3
"""Build and advance validated #113 PROMOTE release-handoff evidence.

This module performs no Git push, GitHub Release or Cloudflare operation.  It
only constructs immutable release evidence around actions performed elsewhere:

* PREPARED: promotion plan/pack/site release/rollback/deployment target are all
  content-addressed and connected to current production preconditions;
* PUBLISHED_UNVERIFIED: a deployment was attempted but live proof is not yet
  sufficient for delivery;
* VERIFIED_LIVE: deployment identity and every required production probe match;
* ROLLED_BACK: an attempted publication restored the exact production-before
  identities.

Every state is validated through RELEASE_HANDOFF_CONTRACT.json.  Outputs are
new files only; existing handoff evidence is never overwritten in place.
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.training.build_release_handoff import (
    HANDOFF_SCHEMA,
    _resolve_snapshot_sha,
    git_head,
    rel,
    sha256_file,
)
from tools.validate_release_handoff import (
    DEFAULT_CONTRACT,
    is_production_url,
    load_json,
    validate_handoff,
)

ROOT = Path(__file__).resolve().parents[2]
HEX40 = re.compile(r"^[0-9a-f]{40}$")
PLAN_SCHEMA = "poker-atomic-promotion/v1"


def _path(root: Path, value: str | Path) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _need_file(path: Path, field: str) -> Path:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"{field} must be a regular file: {path}")
    return path


def _promotion_authorized(decision: Mapping[str, Any]) -> bool:
    if decision.get("promotion_authorized") is True:
        return True
    for key in ("outcome", "decision", "release_outcome"):
        if str(decision.get(key) or "").upper() == "PROMOTE":
            return True
    gate = decision.get("gate")
    if isinstance(gate, Mapping):
        status = str(gate.get("status") or gate.get("decision") or "").upper()
        if gate.get("promotion_ready") is True and status in {"PASS", "READY", "PROMOTE"}:
            return True
    return False


def _validate_candidate_release(path: Path) -> None:
    release = load_json(path)
    if release.get("schema") != "poker-site-release/v3":
        raise ValueError("candidate site release must use poker-site-release/v3")
    publication = release.get("publication_verification") or {}
    if publication.get("status") != "UNVERIFIED_LIVE":
        raise ValueError("candidate site release must remain UNVERIFIED_LIVE before deployment")


def _validate_plan(
    *,
    root: Path,
    plan_path: Path,
    candidate_site_release_path: Path,
    production_site_release_path: Path,
    population_registry_path: Path,
) -> dict[str, Any]:
    plan = load_json(plan_path)
    if plan.get("schema") != PLAN_SCHEMA:
        raise ValueError(f"promotion plan must use {PLAN_SCHEMA}")
    operations = list(plan.get("operations") or [])
    if not operations:
        raise ValueError("promotion plan requires operations")

    prod_release_rel = rel(root, production_site_release_path)
    prod_registry_rel = rel(root, population_registry_path)
    candidate_release_sha = sha256_file(candidate_site_release_path)
    production_release_sha = sha256_file(production_site_release_path)
    production_registry_sha = sha256_file(population_registry_path)

    release_ops: list[tuple[int, Mapping[str, Any]]] = []
    registry_ops: list[tuple[int, Mapping[str, Any]]] = []
    for index, op0 in enumerate(operations):
        if not isinstance(op0, Mapping):
            raise ValueError(f"promotion operation {index} must be an object")
        op = dict(op0)
        source = _need_file(_path(root, str(op.get("source") or "")), f"promotion operation {index} source")
        declared_source_sha = str(op.get("source_sha256") or "").lower()
        if declared_source_sha != sha256_file(source):
            raise ValueError(f"promotion operation {index} source hash mismatch")
        destination = str(op.get("destination") or "")
        if destination == prod_release_rel:
            release_ops.append((index, op))
            if source.resolve() != candidate_site_release_path.resolve():
                raise ValueError("site/RELEASE promotion source is not candidate_site_release")
            if declared_source_sha != candidate_release_sha:
                raise ValueError("candidate site release hash differs from promotion plan")
            if str(op.get("destination_sha256_before") or "").lower() != production_release_sha:
                raise ValueError("site/RELEASE promotion precondition differs from production-before")
        if destination == prod_registry_rel:
            registry_ops.append((index, op))
            if str(op.get("destination_sha256_before") or "").lower() != production_registry_sha:
                raise ValueError("population registry promotion precondition differs from production-before")

    if len(release_ops) != 1:
        raise ValueError("promotion plan must contain exactly one candidate site-release operation")
    if len(registry_ops) > 1:
        raise ValueError("promotion plan may contain at most one population-registry operation")
    if registry_ops and registry_ops[0][0] != len(operations) - 1:
        raise ValueError("population registry mutation must be the final promotion operation")
    return plan


def build_prepared_promote_handoff(
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
    promotion_plan_path: Path,
    candidate_pack_path: Path,
    candidate_site_release_path: Path,
    expected_release_commit_sha: str,
    wrangler_config_path: Path,
    production_url: str,
    contract_path: Path = DEFAULT_CONTRACT,
) -> tuple[dict[str, Any], dict[str, Any]]:
    root = Path(root).resolve()
    cycle_decision_path = _need_file(Path(cycle_decision_path).resolve(), "cycle_decision")
    site_release_path = _need_file(Path(site_release_path).resolve(), "site_release")
    population_registry_path = _need_file(Path(population_registry_path).resolve(), "population_registry")
    promotion_plan_path = _need_file(Path(promotion_plan_path).resolve(), "promotion_plan")
    candidate_pack_path = _need_file(Path(candidate_pack_path).resolve(), "candidate_pack")
    candidate_site_release_path = _need_file(Path(candidate_site_release_path).resolve(), "candidate_site_release")
    wrangler_config_path = _need_file(Path(wrangler_config_path).resolve(), "wrangler_config")
    contract_path = _need_file(Path(contract_path).resolve(), "release_handoff_contract")

    if not population_id.strip() or not cycle_run_id.strip():
        raise ValueError("population_id and cycle_run_id are required")
    decision = load_json(cycle_decision_path)
    observed_population = decision.get("population_id")
    if observed_population not in (None, "") and str(observed_population) != str(population_id):
        raise ValueError("cycle decision population mismatch")
    if not _promotion_authorized(decision):
        raise ValueError("cycle decision does not explicitly authorize PROMOTE")

    commit = str(source_commit_sha or git_head(root)).lower()
    if not HEX40.fullmatch(commit):
        raise ValueError("source_commit_sha must be 40 lowercase hexadecimal characters")
    expected_release_commit_sha = str(expected_release_commit_sha).lower()
    if not HEX40.fullmatch(expected_release_commit_sha):
        raise ValueError("expected_release_commit_sha must be 40 lowercase hexadecimal characters")
    snapshot_sha = _resolve_snapshot_sha(snapshot, snapshot_sha256)
    if not is_production_url(production_url):
        raise ValueError("production_url must be the canonical production HTTPS URL, not a preview")

    _validate_candidate_release(candidate_site_release_path)
    _validate_plan(
        root=root,
        plan_path=promotion_plan_path,
        candidate_site_release_path=candidate_site_release_path,
        production_site_release_path=site_release_path,
        population_registry_path=population_registry_path,
    )

    before = {
        "site_release": {"path": rel(root, site_release_path), "sha256": sha256_file(site_release_path)},
        "population_registry": {"path": rel(root, population_registry_path), "sha256": sha256_file(population_registry_path)},
    }
    document = {
        "schema": HANDOFF_SCHEMA,
        "outcome": "PROMOTE",
        "state": "PREPARED",
        "promotion_authorized": True,
        "population_id": str(population_id),
        "cycle_run_id": str(cycle_run_id),
        "snapshot_sha256": snapshot_sha,
        "source_commit_sha": commit,
        "cycle_decision": {
            "path": rel(root, cycle_decision_path),
            "sha256": sha256_file(cycle_decision_path),
        },
        "production_before": before,
        "promotion": {
            "plan": {"path": rel(root, promotion_plan_path), "sha256": sha256_file(promotion_plan_path)},
            "candidate_pack": {"path": rel(root, candidate_pack_path), "sha256": sha256_file(candidate_pack_path)},
            "candidate_site_release": {
                "path": rel(root, candidate_site_release_path),
                "sha256": sha256_file(candidate_site_release_path),
            },
            "expected_release_commit_sha": expected_release_commit_sha,
        },
        "rollback": {
            "site_release_sha256": before["site_release"]["sha256"],
            "population_registry_sha256": before["population_registry"]["sha256"],
            "performed": False,
        },
        "deployment": {
            "attempted": False,
            "provider": "CLOUDFLARE_WORKERS",
            "static_root": "site",
            "wrangler_config": {
                "path": rel(root, wrangler_config_path),
                "sha256": sha256_file(wrangler_config_path),
            },
            "production_url": str(production_url),
        },
    }
    validation = validate_handoff(document, load_json(contract_path))
    if validation["status"] != "PASS" or validation["delivered"] is not False:
        raise ValueError("generated PREPARED handoff failed release contract: " + "; ".join(validation["errors"]))
    return document, validation


def _validated_transition(
    document: Mapping[str, Any],
    *,
    state: str,
    deployment_evidence: Mapping[str, Any],
    live_verification: Mapping[str, Any] | None,
    rollback_evidence: Mapping[str, Any] | None,
    contract: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    if document.get("schema") != HANDOFF_SCHEMA or document.get("outcome") != "PROMOTE":
        raise ValueError("transition input must be a PROMOTE release handoff")
    if document.get("state") not in {"PREPARED", "PUBLISHED_UNVERIFIED"}:
        raise ValueError("only PREPARED/PUBLISHED_UNVERIFIED handoffs may advance")
    out = copy.deepcopy(dict(document))
    deployment = out.setdefault("deployment", {})
    deployment["attempted"] = True
    for field in ("deployed_commit_sha", "provider_build_id", "provider_version_id"):
        if field in deployment_evidence:
            deployment[field] = deployment_evidence[field]

    if state == "PUBLISHED_UNVERIFIED":
        out["state"] = state
        out.pop("live_verification", None)
    elif state == "VERIFIED_LIVE":
        if live_verification is None:
            raise ValueError("VERIFIED_LIVE requires live_verification evidence")
        out["state"] = state
        out["live_verification"] = copy.deepcopy(dict(live_verification))
    elif state == "ROLLED_BACK":
        if rollback_evidence is None:
            raise ValueError("ROLLED_BACK requires rollback evidence")
        out["state"] = state
        out["rollback"].update(copy.deepcopy(dict(rollback_evidence)))
        out.pop("live_verification", None)
    else:
        raise ValueError(f"unsupported promote handoff state {state!r}")

    validation = validate_handoff(out, contract)
    if validation["status"] != "PASS":
        raise ValueError("release transition failed contract: " + "; ".join(validation["errors"]))
    return out, validation


def record_published_handoff(document, deployment_evidence, contract):
    return _validated_transition(
        document,
        state="PUBLISHED_UNVERIFIED",
        deployment_evidence=deployment_evidence,
        live_verification=None,
        rollback_evidence=None,
        contract=contract,
    )


def record_verified_live_handoff(document, deployment_evidence, live_verification, contract):
    result, validation = _validated_transition(
        document,
        state="VERIFIED_LIVE",
        deployment_evidence=deployment_evidence,
        live_verification=live_verification,
        rollback_evidence=None,
        contract=contract,
    )
    if validation["delivered"] is not True:
        raise ValueError("VERIFIED_LIVE must be delivered")
    return result, validation


def record_rolled_back_handoff(document, deployment_evidence, rollback_evidence, contract):
    result, validation = _validated_transition(
        document,
        state="ROLLED_BACK",
        deployment_evidence=deployment_evidence,
        live_verification=None,
        rollback_evidence=rollback_evidence,
        contract=contract,
    )
    if validation["delivered"] is not False:
        raise ValueError("ROLLED_BACK must not be delivered")
    return result, validation


def _write_new(path: Path, value: Mapping[str, Any]) -> None:
    path = Path(path)
    if path.exists():
        raise FileExistsError(f"refusing to overwrite existing handoff evidence: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    prepare = sub.add_parser("prepare")
    prepare.add_argument("--root", type=Path, default=ROOT)
    prepare.add_argument("--population-id", required=True)
    prepare.add_argument("--cycle-run-id", required=True)
    prepare.add_argument("--cycle-decision", type=Path, required=True)
    snap = prepare.add_mutually_exclusive_group(required=True)
    snap.add_argument("--snapshot", type=Path)
    snap.add_argument("--snapshot-sha256")
    prepare.add_argument("--site-release", type=Path, default=Path("site/RELEASE.json"))
    prepare.add_argument("--population-registry", type=Path, default=Path("training/populations/registry.json"))
    prepare.add_argument("--source-commit-sha")
    prepare.add_argument("--promotion-plan", type=Path, required=True)
    prepare.add_argument("--candidate-pack", type=Path, required=True)
    prepare.add_argument("--candidate-site-release", type=Path, required=True)
    prepare.add_argument("--expected-release-commit-sha", required=True)
    prepare.add_argument("--wrangler-config", type=Path, default=Path("wrangler.jsonc"))
    prepare.add_argument("--production-url", required=True)
    prepare.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    prepare.add_argument("--out", type=Path, required=True)

    for name in ("published", "verified-live", "rolled-back"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--root", type=Path, default=ROOT)
        cmd.add_argument("--handoff", type=Path, required=True)
        cmd.add_argument("--deployment-evidence", type=Path, required=True)
        if name == "verified-live":
            cmd.add_argument("--live-verification", type=Path, required=True)
        if name == "rolled-back":
            cmd.add_argument("--rollback-evidence", type=Path, required=True)
        cmd.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
        cmd.add_argument("--out", type=Path, required=True)

    args = parser.parse_args()
    root = args.root.resolve()
    contract_path = _resolve(root, args.contract)
    contract = load_json(contract_path)

    if args.command == "prepare":
        document, validation = build_prepared_promote_handoff(
            root=root,
            population_id=args.population_id,
            cycle_run_id=args.cycle_run_id,
            cycle_decision_path=_resolve(root, args.cycle_decision),
            snapshot=None if args.snapshot is None else _resolve(root, args.snapshot),
            snapshot_sha256=args.snapshot_sha256,
            site_release_path=_resolve(root, args.site_release),
            population_registry_path=_resolve(root, args.population_registry),
            source_commit_sha=args.source_commit_sha,
            promotion_plan_path=_resolve(root, args.promotion_plan),
            candidate_pack_path=_resolve(root, args.candidate_pack),
            candidate_site_release_path=_resolve(root, args.candidate_site_release),
            expected_release_commit_sha=args.expected_release_commit_sha,
            wrangler_config_path=_resolve(root, args.wrangler_config),
            production_url=args.production_url,
            contract_path=contract_path,
        )
    else:
        document = load_json(_resolve(root, args.handoff))
        deployment = load_json(_resolve(root, args.deployment_evidence))
        if args.command == "published":
            document, validation = record_published_handoff(document, deployment, contract)
        elif args.command == "verified-live":
            live = load_json(_resolve(root, args.live_verification))
            document, validation = record_verified_live_handoff(document, deployment, live, contract)
        else:
            rollback = load_json(_resolve(root, args.rollback_evidence))
            document, validation = record_rolled_back_handoff(document, deployment, rollback, contract)

    output = _resolve(root, args.out)
    _write_new(output, document)
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

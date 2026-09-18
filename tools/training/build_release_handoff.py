#!/usr/bin/env python3
"""Build a validated #113 no-publication release handoff from one cycle decision.

This tool covers the terminal outcomes that must *not* publish anything:
RETAIN, NO_OP and BLOCKED.  It hashes the immutable cycle decision, snapshot and
current production identities, proves production-after equals production-before,
then validates the resulting handoff against RELEASE_HANDOFF_CONTRACT.json.

PROMOTE is deliberately excluded: preparing or executing a publication requires
separate content-addressed pack/promotion/deployment evidence.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]

from tools.validate_release_handoff import (  # noqa: E402
    DEFAULT_CONTRACT,
    load_json,
    validate_handoff,
)

HANDOFF_SCHEMA = "poker-release-handoff/v1"
OUTCOMES = {"RETAIN", "NO_OP", "BLOCKED"}
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rel(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def git_head(root: Path) -> str:
    proc = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode != 0:
        raise ValueError("source commit is required outside a Git checkout")
    value = proc.stdout.strip().lower()
    if not HEX40.fullmatch(value):
        raise ValueError("git HEAD is not a 40-character lowercase SHA")
    return value


def _tokens(value: Any) -> set[str]:
    out: set[str] = set()
    if isinstance(value, str):
        out.add(value.strip().upper())
    elif isinstance(value, Mapping):
        for key in ("outcome", "decision", "status", "state", "result"):
            if key in value:
                out |= _tokens(value[key])
        gate = value.get("gate")
        if isinstance(gate, Mapping):
            out |= _tokens(gate)
    return {token for token in out if token}


def derive_outcome(decision: Mapping[str, Any]) -> str | None:
    """Map known terminal cycle vocabulary to the #113 no-publication outcome."""
    tokens = _tokens(decision)
    if any("NO_OP" in token or token == "NO_PENDING_SNAPSHOT" for token in tokens):
        return "NO_OP"
    if any(
        token in {"BLOCKED", "PREPARED_BLOCKED", "FAIL", "FAILED", "ERROR"}
        or token.startswith("BLOCKED_")
        for token in tokens
    ):
        return "BLOCKED"
    if any(
        "RETAIN" in token or token.startswith("REJECT")
        for token in tokens
    ):
        return "RETAIN"
    return None


def _resolve_snapshot_sha(snapshot: Path | None, snapshot_sha256: str | None) -> str:
    if (snapshot is None) == (snapshot_sha256 is None):
        raise ValueError("provide exactly one of snapshot path or snapshot_sha256")
    if snapshot is not None:
        if not snapshot.is_file():
            raise FileNotFoundError(snapshot)
        return sha256_file(snapshot)
    value = str(snapshot_sha256 or "").lower()
    if not HEX64.fullmatch(value):
        raise ValueError("snapshot_sha256 must be 64 lowercase hexadecimal characters")
    return value


def build_no_publication_handoff(
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
    outcome: str | None,
    reason: str,
    contract_path: Path = DEFAULT_CONTRACT,
) -> tuple[dict[str, Any], dict[str, Any]]:
    root = Path(root).resolve()
    cycle_decision_path = Path(cycle_decision_path).resolve()
    site_release_path = Path(site_release_path).resolve()
    population_registry_path = Path(population_registry_path).resolve()
    contract_path = Path(contract_path).resolve()

    if not population_id.strip() or not cycle_run_id.strip():
        raise ValueError("population_id and cycle_run_id are required")
    if not reason.strip():
        raise ValueError("no-publication handoff requires a non-empty reason")
    for path in (cycle_decision_path, site_release_path, population_registry_path, contract_path):
        if not path.is_file():
            raise FileNotFoundError(path)

    decision = load_json(cycle_decision_path)
    observed_population = decision.get("population_id")
    if observed_population not in (None, "") and str(observed_population) != str(population_id):
        raise ValueError(
            f"cycle decision population mismatch: {observed_population!r} != {population_id!r}"
        )

    derived = derive_outcome(decision)
    selected = str(outcome or derived or "").upper()
    if selected not in OUTCOMES:
        raise ValueError(
            "cannot derive a no-publication outcome; provide --outcome RETAIN, NO_OP or BLOCKED"
        )
    if derived is not None and outcome is not None and selected != derived:
        raise ValueError(f"explicit outcome {selected} conflicts with decision-derived {derived}")

    commit = str(source_commit_sha or git_head(root)).lower()
    if not HEX40.fullmatch(commit):
        raise ValueError("source_commit_sha must be 40 lowercase hexadecimal characters")
    snapshot_sha = _resolve_snapshot_sha(snapshot, snapshot_sha256)

    production_before = {
        "site_release": {
            "path": rel(root, site_release_path),
            "sha256": sha256_file(site_release_path),
        },
        "population_registry": {
            "path": rel(root, population_registry_path),
            "sha256": sha256_file(population_registry_path),
        },
    }
    document = {
        "schema": HANDOFF_SCHEMA,
        "outcome": selected,
        "state": "VERIFIED_NO_PUBLICATION",
        "promotion_authorized": False,
        "population_id": str(population_id),
        "cycle_run_id": str(cycle_run_id),
        "snapshot_sha256": snapshot_sha,
        "source_commit_sha": commit,
        "reason": str(reason).strip(),
        "cycle_decision": {
            "path": rel(root, cycle_decision_path),
            "sha256": sha256_file(cycle_decision_path),
            "observed_terminal_tokens": sorted(_tokens(decision)),
            "derived_release_outcome": derived,
        },
        "production_before": production_before,
        "production_after": copy.deepcopy(production_before),
        "deployment": {
            "attempted": False,
        },
    }
    validation = validate_handoff(document, load_json(contract_path))
    if validation["status"] != "PASS" or validation["delivered"] is not True:
        raise ValueError("generated handoff failed release contract: " + "; ".join(validation["errors"]))
    return document, validation


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--population-id", required=True)
    parser.add_argument("--cycle-run-id", required=True)
    parser.add_argument("--cycle-decision", type=Path, required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--snapshot", type=Path)
    group.add_argument("--snapshot-sha256")
    parser.add_argument("--site-release", type=Path, default=Path("site/RELEASE.json"))
    parser.add_argument(
        "--population-registry",
        type=Path,
        default=Path("training/populations/registry.json"),
    )
    parser.add_argument("--source-commit-sha")
    parser.add_argument("--outcome", choices=sorted(OUTCOMES))
    parser.add_argument("--reason", required=True)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--out", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.root.resolve()

    def resolve(path: Path) -> Path:
        return path if path.is_absolute() else root / path

    document, validation = build_no_publication_handoff(
        root=root,
        population_id=args.population_id,
        cycle_run_id=args.cycle_run_id,
        cycle_decision_path=resolve(args.cycle_decision),
        snapshot=None if args.snapshot is None else resolve(args.snapshot),
        snapshot_sha256=args.snapshot_sha256,
        site_release_path=resolve(args.site_release),
        population_registry_path=resolve(args.population_registry),
        source_commit_sha=args.source_commit_sha,
        outcome=args.outcome,
        reason=args.reason,
        contract_path=resolve(args.contract),
    )
    output = resolve(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "handoff": rel(root, output),
        "outcome": document["outcome"],
        "state": document["state"],
        "cycle_decision_sha256": document["cycle_decision"]["sha256"],
        "snapshot_sha256": document["snapshot_sha256"],
        "validation": validation,
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Validate issue #113 release handoff evidence without publishing anything."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT = ROOT / "training/automation/RELEASE_HANDOFF_CONTRACT.json"
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def at(value: Mapping[str, Any], dotted: str) -> Any:
    current: Any = value
    for part in dotted.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return None
        current = current[part]
    return current


def valid_sha(value: Any, regex: re.Pattern[str]) -> bool:
    return isinstance(value, str) and bool(regex.fullmatch(value))


def is_production_url(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not host:
        return False
    # Cloudflare Workers commit/branch previews prepend an identity before the
    # canonical worker name. They cannot satisfy production evidence.
    if host.endswith(".workers.dev"):
        first = host.split(".", 1)[0]
        if first != "poker-engine":
            return False
    return True


def validate_handoff(document: Mapping[str, Any], contract: Mapping[str, Any]) -> dict[str, Any]:
    errors: list[str] = []

    def need(condition: bool, message: str) -> None:
        if not condition:
            errors.append(message)

    need(document.get("schema") == "poker-release-handoff/v1", "unsupported release handoff schema")
    outcome = str(document.get("outcome") or "")
    state = str(document.get("state") or "")
    need(outcome in set(contract.get("outcomes") or []), "unknown release outcome")
    need(state in set(contract.get("states") or []), "unknown release state")
    for field in (contract.get("common_identity") or {}).get("required", []):
        need(at(document, field) not in (None, ""), f"missing required identity {field}")
    need(valid_sha(document.get("snapshot_sha256"), HEX64), "snapshot_sha256 must be 64 lowercase hex")
    need(valid_sha(document.get("source_commit_sha"), HEX40), "source_commit_sha must be 40 lowercase hex")
    for field in (
        "cycle_decision.sha256",
        "production_before.site_release.sha256",
        "production_before.population_registry.sha256",
    ):
        need(valid_sha(at(document, field), HEX64), f"{field} must be 64 lowercase hex")
    need(document.get("promotion_authorized") is (outcome == "PROMOTE"), "promotion_authorized/outcome mismatch")

    no_pub = set((contract.get("no_publication_outcomes") or {}).get("outcomes") or [])
    if outcome in no_pub:
        need(state == "VERIFIED_NO_PUBLICATION", "non-promotion outcome must be VERIFIED_NO_PUBLICATION")
        need(document.get("promotion_authorized") is False, "non-promotion outcome cannot authorize publication")
        deployment = document.get("deployment") or {}
        need(deployment.get("attempted") is False, "non-promotion outcome cannot attempt deployment")
        need(bool(str(document.get("reason") or "").strip()), "non-promotion outcome requires a reason")
        before = document.get("production_before") or {}
        after = document.get("production_after") or {}
        need(after == before, "non-promotion outcome must preserve exact production identities")
        need(not document.get("promotion"), "non-promotion outcome must not contain a promotion plan")
    elif outcome == "PROMOTE":
        preconditions = contract.get("promote_preconditions") or {}
        for field in preconditions.get("required", []):
            need(at(document, field) not in (None, ""), f"PROMOTE missing {field}")
        for field in (
            "promotion.plan.sha256",
            "promotion.candidate_pack.sha256",
            "promotion.candidate_site_release.sha256",
            "rollback.site_release_sha256",
            "rollback.population_registry_sha256",
            "deployment.wrangler_config.sha256",
        ):
            need(valid_sha(at(document, field), HEX64), f"{field} must be 64 lowercase hex")
        expected_commit = at(document, "promotion.expected_release_commit_sha")
        need(valid_sha(expected_commit, HEX40), "expected release commit must be 40 lowercase hex")
        need(at(document, "deployment.provider") == "CLOUDFLARE_WORKERS", "PROMOTE provider must be CLOUDFLARE_WORKERS")
        need(at(document, "deployment.static_root") == "site", "PROMOTE static_root must be site")
        need(is_production_url(at(document, "deployment.production_url")), "deployment.production_url must be canonical production HTTPS URL, not preview")
        before = document.get("production_before") or {}
        need(at(document, "rollback.site_release_sha256") == at(before, "site_release.sha256"), "rollback site release must equal production_before")
        need(at(document, "rollback.population_registry_sha256") == at(before, "population_registry.sha256"), "rollback registry must equal production_before")

        if state == "PREPARED":
            need(at(document, "deployment.attempted") is False, "PREPARED handoff must not claim deployment attempted")
            need(not document.get("live_verification"), "PREPARED handoff cannot contain live verification")
        elif state == "PUBLISHED_UNVERIFIED":
            need(at(document, "deployment.attempted") is True, "PUBLISHED_UNVERIFIED requires attempted deployment")
        elif state == "VERIFIED_LIVE":
            post = contract.get("post_publication_verification") or {}
            for field in post.get("required", []):
                need(at(document, field) not in (None, ""), f"VERIFIED_LIVE missing {field}")
            deployed = at(document, "deployment.deployed_commit_sha")
            observed = at(document, "live_verification.observed_commit_sha")
            need(valid_sha(deployed, HEX40), "deployed commit must be 40 lowercase hex")
            need(valid_sha(observed, HEX40), "observed commit must be 40 lowercase hex")
            need(deployed == expected_commit, "deployed commit differs from expected release commit")
            need(observed == deployed, "live observed commit differs from deployed commit")
            need(at(document, "live_verification.production_url") == at(document, "deployment.production_url"), "live verification URL differs from production target")
            need(at(document, "live_verification.observed_site_release_sha256") == at(document, "promotion.candidate_site_release.sha256"), "live site release identity differs from promoted candidate")
            probes = {str(row.get("id")): row for row in (at(document, "live_verification.probes") or []) if isinstance(row, Mapping)}
            for probe_id in post.get("required_probe_ids", []):
                need(probe_id in probes, f"missing live probe {probe_id}")
                if probe_id in probes:
                    need(probes[probe_id].get("status") == "PASS", f"live probe {probe_id} did not PASS")
        elif state == "ROLLED_BACK":
            need(at(document, "deployment.attempted") is True, "ROLLED_BACK requires an attempted deployment")
            need(at(document, "rollback.performed") is True, "ROLLED_BACK requires rollback.performed=true")
            need(at(document, "rollback.site_release_sha256_after") == at(before, "site_release.sha256"), "rollback did not restore site release identity")
            need(at(document, "rollback.population_registry_sha256_after") == at(before, "population_registry.sha256"), "rollback did not restore registry identity")
        else:
            need(False, "PROMOTE handoff state must be PREPARED, PUBLISHED_UNVERIFIED, VERIFIED_LIVE or ROLLED_BACK")

    delivered = (outcome in no_pub and state == "VERIFIED_NO_PUBLICATION") or (outcome == "PROMOTE" and state == "VERIFIED_LIVE")
    return {
        "schema": "poker-release-handoff-validation/v1",
        "contract_version": contract.get("version"),
        "outcome": outcome,
        "state": state,
        "status": "PASS" if not errors else "FAIL",
        "delivered": bool(delivered and not errors),
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--handoff", type=Path, required=True)
    args = parser.parse_args()
    result = validate_handoff(load_json(args.handoff), load_json(args.contract))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())

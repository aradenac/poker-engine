#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any

SCHEMA = "poker-parallel-agents/v1"
SLOTS = tuple("ABCDEFGH")
REPORT_SCHEMA = "poker-parallel-scope-report/v1"


def load_contract(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    validate_contract(value)
    return value


def validate_contract(contract: dict[str, Any]) -> None:
    if contract.get("schema") != SCHEMA:
        raise ValueError(f"contract.schema must be {SCHEMA!r}")
    lanes = contract.get("lanes")
    if not isinstance(lanes, dict) or set(lanes) != set(SLOTS):
        raise ValueError("contract.lanes must contain exactly slots A-H")
    valid_statuses = set(contract.get("lane_status_values", []))
    if not valid_statuses:
        raise ValueError("lane_status_values must be non-empty")
    for slot in SLOTS:
        lane = lanes[slot]
        if not isinstance(lane, dict):
            raise ValueError(f"lane {slot} must be an object")
        if not isinstance(lane.get("conflict_group"), str) or not lane["conflict_group"]:
            raise ValueError(f"lane {slot} requires conflict_group")
        if lane.get("status") not in valid_statuses:
            raise ValueError(f"lane {slot} has invalid status")
        for key in ("reserved_paths", "forbidden_paths", "typical_issues"):
            if not isinstance(lane.get(key), list):
                raise ValueError(f"lane {slot}.{key} must be a list")
    for hotspot in contract.get("exclusive_hotspots", []):
        if not isinstance(hotspot, dict) or hotspot.get("owner") not in lanes:
            raise ValueError("exclusive_hotspots entries require a valid owner")
        if not isinstance(hotspot.get("glob"), str) or not hotspot["glob"]:
            raise ValueError("exclusive_hotspots entries require glob")


def _glob_regex(pattern: str) -> re.Pattern[str]:
    out = ["^"]
    i = 0
    while i < len(pattern):
        char = pattern[i]
        if char == "*":
            if i + 1 < len(pattern) and pattern[i + 1] == "*":
                i += 2
                if i < len(pattern) and pattern[i] == "/":
                    out.append("(?:.*/)?")
                    i += 1
                else:
                    out.append(".*")
                continue
            out.append("[^/]*")
        elif char == "?":
            out.append("[^/]")
        else:
            out.append(re.escape(char))
        i += 1
    out.append("$")
    return re.compile("".join(out))


def _normalize_path(path: str) -> str:
    normalized = path.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def glob_match(path: str, pattern: str) -> bool:
    return bool(_glob_regex(pattern).match(_normalize_path(path)))


def _matches(path: str, patterns: list[str]) -> list[str]:
    return [pattern for pattern in patterns if glob_match(path, pattern)]


def _violation(file: str, expected_owner: str | None, rule: str, reference: str | None, detail: str) -> dict[str, Any]:
    return {"file": file, "expected_owner": expected_owner, "rule": rule, "reference": reference, "detail": detail}


def _warning(file: str, rule: str, reference: str | None, detail: str) -> dict[str, Any]:
    return {"file": file, "rule": rule, "reference": reference, "detail": detail}


def _hotspot_for(contract: dict[str, Any], path: str) -> dict[str, Any] | None:
    matches = [item for item in contract.get("exclusive_hotspots", []) if glob_match(path, item["glob"])]
    if not matches:
        return None
    owners = {item["owner"] for item in matches}
    if len(owners) > 1:
        return {
            "owner": None,
            "rule": "AMBIGUOUS_EXCLUSIVE_HOTSPOT",
            "reference": "#225",
            "glob": ", ".join(sorted(item["glob"] for item in matches)),
        }
    return sorted(matches, key=lambda item: (-len(item["glob"]), item["glob"]))[0]


def check_scope(contract: dict[str, Any], slot: str, files: list[str]) -> dict[str, Any]:
    validate_contract(contract)
    slot = slot.upper()
    if slot not in contract["lanes"]:
        raise ValueError(f"unknown slot {slot!r}; expected A-H")

    normalized_files = sorted({_normalize_path(item) for item in files if isinstance(item, str) and item.strip()})
    violations: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    groups: dict[str, set[str]] = {}
    lane = contract["lanes"][slot]

    for path in normalized_files:
        hotspot = _hotspot_for(contract, path)
        if hotspot is not None:
            owner = hotspot.get("owner")
            if owner is None:
                violations.append(_violation(
                    path, None, "AMBIGUOUS_EXCLUSIVE_HOTSPOT", hotspot.get("reference"),
                    f"path matches incompatible exclusive hotspot rules: {hotspot.get('glob')}",
                ))
                continue
            group = contract["lanes"][owner]["conflict_group"]
            groups.setdefault(group, set()).add(path)
            if owner != slot:
                violations.append(_violation(
                    path, owner, hotspot.get("rule", "EXCLUSIVE_HOTSPOT"), hotspot.get("reference"),
                    f"exclusive hotspot belongs to lane {owner} ({group})",
                ))
            continue

        forbidden = [
            item for item in lane.get("forbidden_paths", [])
            if isinstance(item, dict) and glob_match(path, item.get("glob", ""))
        ]
        if forbidden:
            item = sorted(forbidden, key=lambda row: (-len(row.get("glob", "")), row.get("glob", "")))[0]
            owner = item.get("expected_owner")
            if owner in contract["lanes"]:
                groups.setdefault(contract["lanes"][owner]["conflict_group"], set()).add(path)
            violations.append(_violation(
                path, owner, item.get("rule", "FORBIDDEN_PATH"), item.get("reference"),
                f"lane {slot} forbids {item.get('glob')}",
            ))
            continue

        reserved_owners = [
            owner for owner, owner_lane in contract["lanes"].items()
            if _matches(path, owner_lane.get("reserved_paths", []))
        ]
        if len(reserved_owners) > 1:
            owner_text = ",".join(sorted(reserved_owners))
            for owner in reserved_owners:
                groups.setdefault(contract["lanes"][owner]["conflict_group"], set()).add(path)
            violations.append(_violation(
                path, owner_text, "AMBIGUOUS_RESERVED_SCOPE", "#225",
                f"path is reserved by multiple lanes: {owner_text}",
            ))
            continue
        if len(reserved_owners) == 1:
            owner = reserved_owners[0]
            group = contract["lanes"][owner]["conflict_group"]
            groups.setdefault(group, set()).add(path)
            if owner != slot:
                violations.append(_violation(
                    path, owner, "RESERVED_BY_OTHER_LANE", "#225",
                    f"path is reserved by lane {owner} ({group})",
                ))
            continue

        if any(
            isinstance(item, dict) and glob_match(path, item.get("glob", ""))
            for item in contract.get("shared_paths", [])
        ):
            continue

        warnings.append(_warning(
            path, "UNCLASSIFIED_PATH", "#225",
            "path is not assigned to a lane; coordinate before treating it as shared",
        ))

    if len(groups) > 1:
        detail = "; ".join(
            f"{group}: {', '.join(sorted(paths))}" for group, paths in sorted(groups.items())
        )
        violations.append(_violation(
            "<multiple>", slot, "MIXED_CONFLICT_GROUPS", "#225",
            f"one change set spans multiple conflict groups: {detail}",
        ))

    violations.sort(key=lambda item: (
        item["file"], item["rule"], item.get("expected_owner") or "", item.get("reference") or ""
    ))
    warnings.sort(key=lambda item: (item["file"], item["rule"], item.get("reference") or ""))
    status = "FAIL" if violations else ("WARN" if warnings else "PASS")
    return {
        "schema": REPORT_SCHEMA,
        "slot": slot,
        "conflict_group": lane["conflict_group"],
        "lane_status": lane["status"],
        "status": status,
        "files": normalized_files,
        "violations": violations,
        "warnings": warnings,
    }


def files_from_git_range(root: Path, base: str, head: str) -> list[str]:
    process = subprocess.run(
        ["git", "diff", "--name-only", "--no-renames", "--diff-filter=ACMRD", f"{base}...{head}"],
        cwd=root, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    if process.returncode != 0:
        message = process.stderr.strip() or process.stdout.strip() or "git diff failed"
        raise ValueError(f"cannot resolve git range {base}...{head}: {message}")
    return [line.strip() for line in process.stdout.splitlines() if line.strip()]


def stable_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def human_report(report: dict[str, Any]) -> str:
    lines = [
        f"PARALLEL_SCOPE slot={report['slot']} group={report['conflict_group']} "
        f"lane_status={report['lane_status']} status={report['status']}",
        f"FILES ({len(report['files'])}):",
    ]
    lines.extend(f"- {path}" for path in report["files"])
    if not report["files"]:
        lines.append("- none")

    lines.append(f"VIOLATIONS ({len(report['violations'])}):")
    for item in report["violations"]:
        lines.append(
            f"- {item['rule']}: {item['file']} -> expected_owner={item.get('expected_owner') or 'n/a'}; "
            f"ref={item.get('reference') or 'n/a'}; {item['detail']}"
        )
    if not report["violations"]:
        lines.append("- none")

    lines.append(f"WARNINGS ({len(report['warnings'])}):")
    for item in report["warnings"]:
        lines.append(
            f"- {item['rule']}: {item['file']}; ref={item.get('reference') or 'n/a'}; {item['detail']}"
        )
    if not report["warnings"]:
        lines.append("- none")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check a parallel-agent change set against the machine-readable #225 lane scope."
    )
    parser.add_argument("--slot", required=True, choices=SLOTS)
    parser.add_argument("--files", nargs="+")
    parser.add_argument("--base")
    parser.add_argument("--head")
    parser.add_argument("--json", action="store_true", dest="json_output")
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--contract", type=Path, default=None)
    args = parser.parse_args(argv)

    root = (args.root or Path(__file__).resolve().parents[1]).resolve()
    contract_path = (args.contract or root / ".project" / "parallel-agents.json").resolve()
    try:
        contract = load_contract(contract_path)
        explicit = args.files is not None
        ranged = args.base is not None or args.head is not None
        if explicit and ranged:
            raise ValueError("use either --files or --base/--head, not both")
        if explicit:
            files = args.files or []
        else:
            if not args.base or not args.head:
                raise ValueError("provide --files ... or both --base <ref> and --head <ref>")
            files = files_from_git_range(root, args.base, args.head)
        report = check_scope(contract, args.slot, files)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        report = {
            "schema": REPORT_SCHEMA, "slot": args.slot, "conflict_group": None, "lane_status": None,
            "status": "FAIL", "files": [],
            "violations": [{
                "file": "<scope-check>", "expected_owner": None, "rule": "CHECKER_ERROR",
                "reference": "#225", "detail": str(exc),
            }],
            "warnings": [],
        }

    print(stable_json(report) if args.json_output else human_report(report), end="")
    return 1 if report["status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())

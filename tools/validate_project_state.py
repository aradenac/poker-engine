#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

SCHEMA = "poker-project-capabilities/v1"
REPORT_SCHEMA = "poker-project-state-report/v1"
STATES = [
    "CONTRACT_READY",
    "SCIENTIFICALLY_SELECTED",
    "PRODUCT_INTEGRATED",
    "PROMOTED",
    "LIVE",
]
STATE_RANK = {state: rank for rank, state in enumerate(STATES)}


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def _json_pointer(document: Any, pointer: str) -> Any:
    if pointer == "":
        return document
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise ValueError(f"invalid JSON pointer: {pointer!r}")
    current = document
    for raw in pointer.split("/")[1:]:
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            try:
                current = current[int(token)]
            except (ValueError, IndexError) as exc:
                raise KeyError(pointer) from exc
        elif isinstance(current, dict):
            if token not in current:
                raise KeyError(pointer)
            current = current[token]
        else:
            raise KeyError(pointer)
    return current


def _safe_path(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    root = root.resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"path escapes repository root: {relative}") from exc
    return path


def evaluate_check(root: Path, check: dict[str, Any]) -> dict[str, Any]:
    kind = check.get("kind")
    relative = check.get("path")
    if not isinstance(relative, str) or not relative:
        return {"status": "FAIL", "message": "check path must be a non-empty string"}
    try:
        path = _safe_path(root, relative)
    except ValueError as exc:
        return {"status": "FAIL", "message": str(exc)}

    if kind == "path_exists":
        expected_type = check.get("type", "any")
        if not path.exists():
            return {"status": "FAIL", "message": f"missing path: {relative}"}
        if expected_type == "file" and not path.is_file():
            return {"status": "FAIL", "message": f"expected file: {relative}"}
        if expected_type == "dir" and not path.is_dir():
            return {"status": "FAIL", "message": f"expected directory: {relative}"}
        if expected_type not in {"any", "file", "dir"}:
            return {"status": "FAIL", "message": f"unsupported path type: {expected_type}"}
        return {"status": "PASS", "message": f"path exists: {relative}"}

    if kind == "file_contains":
        if not path.is_file():
            return {"status": "FAIL", "message": f"missing file: {relative}"}
        needle = check.get("text")
        if not isinstance(needle, str) or not needle:
            return {"status": "FAIL", "message": "file_contains requires non-empty text"}
        content = path.read_text(encoding="utf-8")
        if needle not in content:
            return {"status": "FAIL", "message": f"{relative} does not contain required text"}
        return {"status": "PASS", "message": f"{relative} contains required text"}

    if kind == "json_equals":
        if not path.is_file():
            return {"status": "FAIL", "message": f"missing JSON file: {relative}"}
        pointer = check.get("pointer")
        if not isinstance(pointer, str):
            return {"status": "FAIL", "message": "json_equals requires pointer"}
        try:
            actual = _json_pointer(load_json(path), pointer)
        except (ValueError, KeyError, json.JSONDecodeError) as exc:
            return {"status": "FAIL", "message": f"{relative}{pointer}: {exc}"}
        expected = check.get("equals")
        if actual != expected:
            return {
                "status": "FAIL",
                "message": f"{relative}{pointer}: expected {expected!r}, got {actual!r}",
            }
        return {"status": "PASS", "message": f"{relative}{pointer} == {expected!r}"}

    return {"status": "FAIL", "message": f"unsupported check kind: {kind!r}"}


def validate_manifest(manifest: dict[str, Any], root: Path) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    rows: list[dict[str, Any]] = []

    if manifest.get("schema") != SCHEMA:
        errors.append(f"schema must be {SCHEMA!r}")
    if manifest.get("state_order") != STATES:
        errors.append("state_order must exactly match the canonical delivery-state order")

    capabilities = manifest.get("capabilities")
    if not isinstance(capabilities, list) or not capabilities:
        errors.append("capabilities must be a non-empty list")
        capabilities = []

    seen: set[str] = set()
    for raw in capabilities:
        if not isinstance(raw, dict):
            errors.append("each capability must be an object")
            continue

        capability_id = raw.get("id")
        state = raw.get("state")
        row = {
            "id": capability_id,
            "state": state,
            "evidence": [],
            "limits": [],
            "administrative_gap": None,
        }

        if not isinstance(capability_id, str) or not capability_id:
            errors.append("capability id must be a non-empty string")
            rows.append(row)
            continue
        if capability_id in seen:
            errors.append(f"{capability_id}: duplicate capability id")
        seen.add(capability_id)

        if state not in STATE_RANK:
            errors.append(f"{capability_id}: invalid state {state!r}")
            rows.append(row)
            continue

        evidence = raw.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            errors.append(f"{capability_id}: at least one evidence check is required")
            evidence = []

        proves_current = False
        for index, item in enumerate(evidence):
            if not isinstance(item, dict):
                errors.append(f"{capability_id}: evidence #{index + 1} must be an object")
                continue
            proves = item.get("proves")
            if proves not in STATE_RANK:
                errors.append(f"{capability_id}: evidence #{index + 1} has invalid proves state")
                continue
            if STATE_RANK[proves] > STATE_RANK[state]:
                errors.append(f"{capability_id}: evidence claims {proves} above declared state {state}")
                continue
            result = evaluate_check(root, item)
            result.update({"id": item.get("id"), "proves": proves})
            row["evidence"].append(result)
            if result["status"] != "PASS":
                errors.append(f"{capability_id}: {result['message']}")
            if proves == state and result["status"] == "PASS":
                proves_current = True

        if not proves_current:
            errors.append(f"{capability_id}: no passing evidence proves current state {state}")

        limits = raw.get("limits", [])
        if not isinstance(limits, list):
            errors.append(f"{capability_id}: limits must be a list")
            limits = []
        for index, item in enumerate(limits):
            if not isinstance(item, dict):
                errors.append(f"{capability_id}: limit #{index + 1} must be an object")
                continue
            blocks_state = item.get("blocks_state")
            if blocks_state not in STATE_RANK:
                errors.append(f"{capability_id}: limit #{index + 1} has invalid blocks_state")
                continue
            if STATE_RANK[blocks_state] <= STATE_RANK[state]:
                errors.append(f"{capability_id}: limit {blocks_state} must be above current state {state}")
                continue
            check = item.get("check")
            if not isinstance(check, dict):
                errors.append(f"{capability_id}: limit #{index + 1} requires a check object")
                continue
            result = evaluate_check(root, check)
            result.update({"id": item.get("id"), "blocks_state": blocks_state})
            row["limits"].append(result)
            if result["status"] != "PASS":
                errors.append(f"{capability_id}: stale/invalid limit: {result['message']}")

        administrative = raw.get("administrative")
        if administrative is not None:
            if not isinstance(administrative, dict):
                errors.append(f"{capability_id}: administrative must be an object")
            else:
                claimed_state = administrative.get("claimed_state")
                status = administrative.get("status")
                if claimed_state not in STATE_RANK:
                    errors.append(f"{capability_id}: invalid administrative claimed_state")
                elif status not in {"OPEN", "CLOSED"}:
                    errors.append(f"{capability_id}: administrative status must be OPEN or CLOSED")
                elif STATE_RANK[claimed_state] > STATE_RANK[state]:
                    issue = administrative.get("issue")
                    message = (
                        f"{capability_id}: issue #{issue} is {status} with claimed "
                        f"{claimed_state}, while versioned evidence declares {state}"
                    )
                    successor = administrative.get("successor_issue")
                    reason = administrative.get("known_mismatch_reason")
                    row["administrative_gap"] = {
                        "issue": issue,
                        "status": status,
                        "claimed_state": claimed_state,
                        "successor_issue": successor,
                        "known_mismatch_reason": reason,
                    }
                    if successor and isinstance(reason, str) and reason.strip():
                        warnings.append(
                            f"{message}; tracked by successor issue #{successor}: {reason.strip()}"
                        )
                    else:
                        errors.append(f"{message}; contradiction is not traceably acknowledged")

        rows.append(row)

    status = "FAIL" if errors else ("WARN" if warnings else "PASS")
    return {
        "schema": REPORT_SCHEMA,
        "manifest_schema": manifest.get("schema"),
        "status": status,
        "errors": errors,
        "warnings": warnings,
        "capabilities": rows,
    }


def exit_code(report: dict[str, Any], strict_warnings: bool = False) -> int:
    if report.get("status") == "FAIL":
        return 1
    if strict_warnings and report.get("status") == "WARN":
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate machine-readable project capability state against versioned evidence."
    )
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--strict-warnings", action="store_true")
    args = parser.parse_args(argv)

    root = (args.root or Path(__file__).resolve().parents[1]).resolve()
    manifest_path = (args.manifest or root / ".project" / "capabilities.json").resolve()
    try:
        manifest = load_json(manifest_path)
        report = validate_manifest(manifest, root)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        report = {
            "schema": REPORT_SCHEMA,
            "status": "FAIL",
            "errors": [str(exc)],
            "warnings": [],
            "capabilities": [],
        }

    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return exit_code(report, strict_warnings=args.strict_warnings)


if __name__ == "__main__":
    raise SystemExit(main())

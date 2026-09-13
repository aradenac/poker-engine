#!/usr/bin/env python3
"""Generate the CSS banner identifying the exact deployed revision.

Cloudflare Workers Builds exposes WORKERS_CI_* variables. Cloudflare Pages and
GitHub Actions fallbacks are also supported so the site remains portable.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import subprocess
from pathlib import Path


def first_env(*names: str) -> str:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""


def git_value(*args: str) -> str:
    try:
        return subprocess.check_output(
            ["git", *args], stderr=subprocess.DEVNULL, text=True
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def css_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def normalized_timestamp() -> tuple[str, str]:
    raw = first_env("DEPLOYMENT_BUILD_TIME")
    if raw:
        try:
            parsed = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=dt.timezone.utc)
            parsed = parsed.astimezone(dt.timezone.utc).replace(microsecond=0)
        except ValueError:
            return raw, raw
    else:
        parsed = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    iso = parsed.isoformat().replace("+00:00", "Z")
    display = parsed.strftime("%Y-%m-%d %H:%M UTC")
    return iso, display


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="site/deployment-meta.css")
    args = parser.parse_args()

    commit = first_env(
        "WORKERS_CI_COMMIT_SHA",
        "CF_PAGES_COMMIT_SHA",
        "GITHUB_SHA",
    ) or git_value("rev-parse", "HEAD")
    branch = first_env(
        "WORKERS_CI_BRANCH",
        "CF_PAGES_BRANCH",
        "GITHUB_REF_NAME",
    ) or git_value("branch", "--show-current")
    build_id = first_env("WORKERS_CI_BUILD_UUID", "CF_PAGES_URL", "GITHUB_RUN_ID")
    generated_at, display_time = normalized_timestamp()

    commit = commit or "unknown"
    branch = branch or "local"
    build_id = build_id or "local"
    short_commit = commit[:12] if commit != "unknown" else commit

    visible = f"déploiement {display_time} · {branch} · commit {short_commit}"
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "\n".join(
            [
                "/* poker-deployment-meta/v1",
                f"commit: {commit}",
                f"branch: {branch}",
                f"build_id: {build_id}",
                f"generated_at: {generated_at}",
                "*/",
                "body::before{",
                f'  content:"{css_escape(visible)}";',
                "  display:block;",
                "  max-width:1220px;",
                "  margin:6px auto -18px;",
                "  padding:0 26px;",
                "  text-align:right;",
                "  color:var(--muted,#9aa7c2);",
                "  font:500 9px/1.35 ui-monospace,SFMono-Regular,Consolas,monospace;",
                "  letter-spacing:.01em;",
                "  opacity:.68;",
                "  pointer-events:none;",
                "}",
                "body.trainer-view-open::before{max-width:1580px;margin-bottom:-8px;padding:0 18px}",
                "@media(max-width:760px){body::before{margin:4px auto -10px;padding:0 10px;font-size:8px}}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(f"wrote {output}: {visible}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
